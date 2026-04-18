"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useBank } from "@/lib/bank-context";
import {
  client,
  CodebaseChunkItem,
  CodebaseChunkDetail,
  CodebaseFileItem,
  CodebaseChunksResult,
  CodebaseFilesResult,
  CodebaseImpactResult,
  CodebaseMemoryIngestMode,
  CodebaseReviewSummary,
  CodebaseSummary,
  CodebaseSymbolsResult,
  CodebaseRepoMapResult,
  CodebaseModuleBriefsResult,
  CodebaseCurateResult,
  CodebaseTriageSettings,
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
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
  ArrowRight,
  Boxes,
  CheckCircle2,
  ChevronsRight,
  ChevronRight,
  FileCode2,
  Files,
  FolderGit2,
  GitBranch,
  HelpCircle,
  Inbox,
  Info,
  Layers3,
  Loader2,
  Map as MapIcon,
  Network,
  RefreshCw,
  Search,
  ShieldCheck,
  Sliders,
  Sparkles,
  Telescope,
  Upload,
  X,
  Zap,
} from "lucide-react";

type ImportTab = "github" | "zip";
type WorkspaceTab =
  | "review"
  | "files"
  | "code_map"
  | "curate"
  | "symbols"
  | "impact"
  | "research"
  | "approved";
type ImpactMode = "path" | "symbol" | "query";

type ChunkOrderBy = "default" | "significance" | "complexity" | "pagerank";

const FILE_ROLE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "all", label: "All roles" },
  { value: "entrypoint", label: "Entrypoint" },
  { value: "api_route", label: "API route" },
  { value: "config", label: "Config" },
  { value: "schema_model", label: "Schema / model" },
  { value: "migration", label: "Migration" },
  { value: "public_lib", label: "Public library" },
  { value: "shared_util", label: "Shared utility" },
  { value: "test", label: "Test" },
  { value: "docs", label: "Docs" },
  { value: "fixture", label: "Fixture" },
  { value: "generated", label: "Generated" },
  { value: "vendored", label: "Vendored" },
  { value: "boilerplate", label: "Boilerplate" },
  { value: "unknown", label: "Unknown" },
];

const ROUTE_SOURCE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "all", label: "Any source" },
  { value: "auto_triage_dismiss", label: "Auto-dismissed" },
  { value: "auto_triage_memory_pending", label: "Auto → memory" },
  { value: "auto_triage_review", label: "Auto-review (gray zone)" },
  { value: "manual", label: "Manual" },
  { value: "inherited", label: "Inherited" },
  { value: "system", label: "System" },
];

const SAFETY_TAG_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "all", label: "Any safety" },
  { value: "auth", label: "Auth" },
  { value: "crypto", label: "Crypto" },
  { value: "sql_string", label: "SQL string" },
  { value: "eval", label: "Eval" },
  { value: "deserialization", label: "Deserialization" },
  { value: "subprocess", label: "Subprocess" },
  { value: "network", label: "Network" },
];

function safetyTagTone(tag: string): string {
  switch (tag) {
    case "auth":
    case "crypto":
      return "bg-amber-500/15 text-amber-600 ring-1 ring-amber-500/30";
    case "sql_string":
    case "eval":
    case "deserialization":
      return "bg-rose-500/15 text-rose-600 ring-1 ring-rose-500/30";
    case "subprocess":
      return "bg-orange-500/15 text-orange-600 ring-1 ring-orange-500/30";
    case "network":
      return "bg-sky-500/15 text-sky-600 ring-1 ring-sky-500/30";
    default:
      return "bg-muted text-muted-foreground ring-1 ring-border";
  }
}

function routeSourceTone(source: string | null | undefined): string {
  switch (source) {
    case "auto_triage_dismiss":
      return "bg-muted text-muted-foreground ring-1 ring-border";
    case "auto_triage_memory_pending":
      return "bg-emerald-500/15 text-emerald-600 ring-1 ring-emerald-500/30";
    case "auto_triage_review":
      return "bg-amber-500/15 text-amber-600 ring-1 ring-amber-500/30";
    case "manual":
      return "bg-indigo-500/15 text-indigo-600 ring-1 ring-indigo-500/30";
    case "inherited":
      return "bg-sky-500/15 text-sky-600 ring-1 ring-sky-500/30";
    case "system":
      return "bg-muted text-muted-foreground ring-1 ring-border";
    default:
      return "bg-muted text-muted-foreground ring-1 ring-border";
  }
}

function formatRouteSource(value: string | null | undefined): string {
  if (!value) return "Manual";
  switch (value) {
    case "auto_triage_dismiss":
      return "Auto-dismissed";
    case "auto_triage_memory_pending":
      return "Auto → memory";
    case "auto_triage_review":
      return "Auto-review";
    case "manual":
      return "Manual";
    case "inherited":
      return "Inherited";
    case "system":
      return "System";
    default:
      return value.replace(/_/g, " ");
  }
}

function formatSignificance(score: number | undefined | null): string {
  if (score === null || score === undefined) return "—";
  return score.toFixed(2);
}

function significanceTone(score: number | undefined | null): string {
  if (score === null || score === undefined) return "text-muted-foreground";
  if (score >= 0.65) return "text-emerald-600 font-semibold";
  if (score >= 0.35) return "text-amber-600 font-semibold";
  return "text-muted-foreground";
}

type ParsedGithubSource = {
  owner: string;
  repo: string;
  ref?: string;
};

type PendingMemoryAction =
  | {
      kind: "route";
      itemIds: string[];
      chunkCount: number;
      previewChunk: CodebaseChunkItem | CodebaseChunkDetail | null;
    }
  | {
      kind: "approve";
      chunkCount: number;
      previewChunk: null;
    };

type RepoMapGroup = {
  directory: string;
  items: CodebaseFileItem[];
  totalBytes: number;
  changedCount: number;
  hydratedCount: number;
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

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  return `${(value / (1024 * 1024)).toFixed(value < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function fileNameFromPath(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] || path;
}

function directoryFromPath(path: string): string {
  const parts = path.split("/").filter(Boolean);
  if (parts.length <= 1) return "repo root";
  return parts.slice(0, -1).join("/");
}

function HoverPath({ value, className = "" }: { value: string; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={`block max-w-full truncate text-left font-mono text-xs text-card-foreground ${className}`.trim()}
          aria-label={value}
          title={value}
        >
          {value}
        </button>
      </TooltipTrigger>
      <TooltipContent
        side="top"
        align="start"
        className="max-w-[min(42rem,calc(100vw-2rem))] break-all font-mono text-xs leading-relaxed"
      >
        {value}
      </TooltipContent>
    </Tooltip>
  );
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
    case "review_in_progress":
    case "pending_approval":
    case "pending":
    case "processing":
    case "parsing":
    case "hydrated_from_previous_snapshot":
      return "bg-amber-500/10 text-amber-700 dark:text-amber-300";
    case "partially_approved":
      return "bg-blue-500/10 text-blue-700 dark:text-blue-300";
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
      : codebase.source_config.repo_url
        ? codebase.source_config.repo_url
        : codebase.name;
  }
  return codebase.name;
}

function routeTone(routeTarget: string | null | undefined): string {
  switch (routeTarget) {
    case "memory":
      return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
    case "research":
      return "bg-blue-500/10 text-blue-700 dark:text-blue-300";
    case "dismissed":
      return "bg-muted text-muted-foreground";
    default:
      return "bg-amber-500/10 text-amber-700 dark:text-amber-300";
  }
}

function memoryIngestModeLabel(mode: CodebaseMemoryIngestMode): string {
  return mode === "retain" ? "Retain Pipeline" : "ASD Direct";
}

function memoryIngestModeDescription(mode: CodebaseMemoryIngestMode): string {
  return mode === "retain"
    ? "Runs the chunk through Atulya retain with ASD-enriched context so memory can form richer links and meaning."
    : "Stores the exact ASD-reviewed chunk directly as deterministic memory for the fastest, lowest-overhead sync.";
}

export function CodebasesView() {
  const { currentBank } = useBank();

  const [importTab, setImportTab] = useState<ImportTab>("github");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("review");
  const [codebases, setCodebases] = useState<CodebaseSummary[]>([]);
  const [loadingCodebases, setLoadingCodebases] = useState(false);
  const [selectedCodebaseId, setSelectedCodebaseId] = useState<string | null>(null);
  const [selectedCodebase, setSelectedCodebase] = useState<CodebaseSummary | null>(null);
  const [loadingSelectedCodebase, setLoadingSelectedCodebase] = useState(false);

  const [activeOperationId, setActiveOperationId] = useState<string | null>(null);
  const [operationStatus, setOperationStatus] = useState<OperationStatus | null>(null);
  const [operationResult, setOperationResult] = useState<OperationResult | null>(null);
  const [cancellingOperation, setCancellingOperation] = useState(false);

  const [githubRepoUrl, setGithubRepoUrl] = useState("");
  const [githubOwner, setGithubOwner] = useState("");
  const [githubRepo, setGithubRepo] = useState("");
  const [githubRef, setGithubRef] = useState("");
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
  const [memoryActionDialogOpen, setMemoryActionDialogOpen] = useState(false);
  const [pendingMemoryAction, setPendingMemoryAction] = useState<PendingMemoryAction | null>(null);
  const [memoryIngestMode, setMemoryIngestMode] = useState<CodebaseMemoryIngestMode>("retain");

  const [reviewSummary, setReviewSummary] = useState<CodebaseReviewSummary | null>(null);
  const [loadingReviewSummary, setLoadingReviewSummary] = useState(false);
  const [chunkQuery, setChunkQuery] = useState("");
  const deferredChunkQuery = useDeferredValue(chunkQuery.trim());
  const [chunkRouteFilter, setChunkRouteFilter] = useState("all");
  const [chunkChangeFilter, setChunkChangeFilter] = useState("all");
  const [chunkKindFilter, setChunkKindFilter] = useState("all");
  const [chunkFileRoleFilter, setChunkFileRoleFilter] = useState("all");
  const [chunkSafetyFilter, setChunkSafetyFilter] = useState("all");
  const [chunkRouteSourceFilter, setChunkRouteSourceFilter] = useState("all");
  const [chunkAutoReasonFilter, setChunkAutoReasonFilter] = useState<string | null>(null);
  const [chunkOrderBy, setChunkOrderBy] = useState<ChunkOrderBy>("default");
  const [chunkMinSignificance, setChunkMinSignificance] = useState<string>("");
  const [chunksResult, setChunksResult] = useState<CodebaseChunksResult | null>(null);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [selectedChunkIds, setSelectedChunkIds] = useState<string[]>([]);
  const [chunkDetail, setChunkDetail] = useState<CodebaseChunkDetail | null>(null);
  const [loadingChunkDetail, setLoadingChunkDetail] = useState(false);
  const [chunkDialogOpen, setChunkDialogOpen] = useState(false);
  const [routingTarget, setRoutingTarget] = useState<
    "memory" | "research" | "dismissed" | "unrouted" | null
  >(null);
  const [researchResult, setResearchResult] = useState<CodebaseChunksResult | null>(null);
  const [loadingResearch, setLoadingResearch] = useState(false);
  const [approvedChunksResult, setApprovedChunksResult] = useState<CodebaseChunksResult | null>(
    null
  );
  const [loadingApprovedChunks, setLoadingApprovedChunks] = useState(false);

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

  const [repoMapResult, setRepoMapResult] = useState<CodebaseRepoMapResult | null>(null);
  const [loadingRepoMap, setLoadingRepoMap] = useState(false);
  const [moduleBriefsResult, setModuleBriefsResult] = useState<CodebaseModuleBriefsResult | null>(
    null
  );
  const [loadingModuleBriefs, setLoadingModuleBriefs] = useState(false);

  const [intentInput, setIntentInput] = useState("");
  const [intentScopeHint, setIntentScopeHint] = useState("");
  const [intentResult, setIntentResult] = useState<CodebaseCurateResult | null>(null);
  const [loadingIntent, setLoadingIntent] = useState(false);

  const [triageSettings, setTriageSettings] = useState<CodebaseTriageSettings | null>(null);
  const [loadingTriageSettings, setLoadingTriageSettings] = useState(false);
  const [triageSettingsOpen, setTriageSettingsOpen] = useState(false);
  const [triageDraft, setTriageDraft] = useState<CodebaseTriageSettings | null>(null);
  const [savingTriageSettings, setSavingTriageSettings] = useState(false);

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

  const loadReviewSummary = async (codebaseId: string) => {
    if (!currentBank) return;
    setLoadingReviewSummary(true);
    try {
      const response = await client.getCodebaseReview(currentBank, codebaseId);
      setReviewSummary(response);
    } catch {
      setReviewSummary(null);
    } finally {
      setLoadingReviewSummary(false);
    }
  };

  const loadChunks = async (codebaseId: string, cursor?: string | null, append = false) => {
    if (!currentBank) return;
    setLoadingChunks(true);
    try {
      const minSigParsed = chunkMinSignificance.trim() ? Number(chunkMinSignificance.trim()) : NaN;
      const response = await client.listCodebaseChunks(currentBank, codebaseId, {
        q: deferredChunkQuery || undefined,
        route_target: chunkRouteFilter === "all" ? undefined : chunkRouteFilter,
        changed_only: chunkChangeFilter === "changed",
        kind: chunkKindFilter === "all" ? undefined : chunkKindFilter,
        file_role: chunkFileRoleFilter === "all" ? undefined : chunkFileRoleFilter,
        has_safety_tag: chunkSafetyFilter === "all" ? undefined : chunkSafetyFilter,
        route_source: chunkRouteSourceFilter === "all" ? undefined : chunkRouteSourceFilter,
        auto_route_reason: chunkAutoReasonFilter || undefined,
        min_significance: Number.isFinite(minSigParsed) ? minSigParsed : undefined,
        order_by: chunkOrderBy === "default" ? undefined : chunkOrderBy,
        limit: 20,
        cursor: cursor || undefined,
      });
      setChunksResult((current) =>
        append && current
          ? {
              ...response,
              items: [...current.items, ...response.items],
            }
          : response
      );
    } catch {
      setChunksResult(null);
    } finally {
      setLoadingChunks(false);
    }
  };

  const loadRepoMap = async (codebaseId: string) => {
    if (!currentBank) return;
    setLoadingRepoMap(true);
    try {
      const response = await client.getCodebaseRepoMap(currentBank, codebaseId);
      setRepoMapResult(response);
    } catch {
      setRepoMapResult(null);
    } finally {
      setLoadingRepoMap(false);
    }
  };

  const loadModuleBriefs = async (codebaseId: string) => {
    if (!currentBank) return;
    setLoadingModuleBriefs(true);
    try {
      const response = await client.listCodebaseModuleBriefs(currentBank, codebaseId);
      setModuleBriefsResult(response);
    } catch {
      setModuleBriefsResult(null);
    } finally {
      setLoadingModuleBriefs(false);
    }
  };

  const loadTriageSettings = async (codebaseId: string) => {
    if (!currentBank) return;
    setLoadingTriageSettings(true);
    try {
      const response = await client.getCodebaseTriageSettings(currentBank, codebaseId);
      setTriageSettings(response.settings);
    } catch {
      setTriageSettings(null);
    } finally {
      setLoadingTriageSettings(false);
    }
  };

  const openTriageSettingsDialog = () => {
    setTriageDraft(
      triageSettings ?? {
        score_threshold_high: 0.62,
        centrality_threshold: 0.35,
        safety_threshold: 0.25,
        embedding_provider: "jina_local",
        enable_safety_scan: true,
        enable_semgrep: false,
        semgrep_rulepack: null,
        scip_index_path: null,
      }
    );
    setTriageSettingsOpen(true);
  };

  const saveTriageSettings = async () => {
    if (!currentBank || !selectedCodebaseId || !triageDraft) return;
    setSavingTriageSettings(true);
    try {
      const response = await client.updateCodebaseTriageSettings(
        currentBank,
        selectedCodebaseId,
        triageDraft
      );
      setTriageSettings(response.settings);
      toast.success("Triage settings updated. Re-index the codebase for new chunks to use them.");
      setTriageSettingsOpen(false);
    } catch {
      toast.error("Failed to update triage settings.");
    } finally {
      setSavingTriageSettings(false);
    }
  };

  const runIntentCuration = async () => {
    if (!currentBank || !selectedCodebaseId) return;
    const intent = intentInput.trim();
    if (!intent) {
      toast.error("Describe the intent you want to curate for.");
      return;
    }
    setLoadingIntent(true);
    try {
      const response = await client.curateCodebaseByIntent(currentBank, selectedCodebaseId, {
        intent,
        scope_hint: intentScopeHint.trim() || null,
        top_k_clusters: 8,
        top_k_symbols: 24,
      });
      setIntentResult(response);
    } catch {
      setIntentResult(null);
    } finally {
      setLoadingIntent(false);
    }
  };

  const loadResearchQueue = async (codebaseId: string, cursor?: string | null, append = false) => {
    if (!currentBank) return;
    setLoadingResearch(true);
    try {
      const response = await client.listCodebaseResearchQueue(currentBank, codebaseId, {
        limit: 20,
        cursor: cursor || undefined,
      });
      setResearchResult((current) =>
        append && current
          ? {
              ...response,
              items: [...current.items, ...response.items],
            }
          : response
      );
    } catch {
      setResearchResult(null);
    } finally {
      setLoadingResearch(false);
    }
  };

  const loadApprovedChunks = async (
    codebaseId: string,
    snapshotId: string,
    cursor?: string | null,
    append = false
  ) => {
    if (!currentBank) return;
    setLoadingApprovedChunks(true);
    try {
      const response = await client.listCodebaseChunks(currentBank, codebaseId, {
        route_target: "memory",
        snapshot_id: snapshotId,
        limit: 20,
        cursor: cursor || undefined,
      });
      setApprovedChunksResult((current) =>
        append && current
          ? {
              ...response,
              items: [...current.items, ...response.items],
            }
          : response
      );
    } catch {
      setApprovedChunksResult(null);
    } finally {
      setLoadingApprovedChunks(false);
    }
  };

  const openChunkDetail = async (chunkId: string) => {
    if (!currentBank || !selectedCodebaseId) return;
    setChunkDialogOpen(true);
    setLoadingChunkDetail(true);
    try {
      const response = await client.getCodebaseChunkDetail(
        currentBank,
        selectedCodebaseId,
        chunkId
      );
      setChunkDetail(response);
    } catch {
      setChunkDetail(null);
    } finally {
      setLoadingChunkDetail(false);
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

  const openMemoryActionDialog = (action: PendingMemoryAction) => {
    setPendingMemoryAction(action);
    setMemoryIngestMode("retain");
    setMemoryActionDialogOpen(true);
  };

  const handleGithubImport = async () => {
    const parsedRepoUrl = parseGithubRepoUrl(githubRepoUrl);
    const effectiveOwner = githubOwner.trim() || parsedRepoUrl?.owner || "";
    const effectiveRepo = githubRepo.trim() || parsedRepoUrl?.repo || "";
    const effectiveRef = githubRef.trim() || parsedRepoUrl?.ref || "";

    if (!currentBank || !effectiveOwner || !effectiveRepo) {
      toast.error("GitHub import needs a repo URL or owner/repo.");
      return;
    }

    setSubmittingGithub(true);
    try {
      const response = await client.importCodebaseGithub(currentBank, {
        owner: effectiveOwner,
        repo: effectiveRepo,
        repo_url: githubRepoUrl.trim() || undefined,
        ref: effectiveRef || undefined,
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
      const refLabel = effectiveRef || "default branch";
      toast.success(`Queued GitHub import for ${effectiveOwner}/${effectiveRepo}@${refLabel}.`);
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

  const handleApprove = async (selectedMode: CodebaseMemoryIngestMode = "direct") => {
    if (!currentBank || !selectedCodebase?.current_snapshot_id) return;

    setApprovingCodebase(true);
    try {
      const response = await client.approveCodebase(currentBank, selectedCodebase.id, {
        snapshot_id: selectedCodebase.current_snapshot_id,
        memory_ingest_mode: selectedMode,
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
      toast.success(
        `Queued ${memoryIngestModeLabel(selectedMode).toLowerCase()} memory hydration for the current reviewed snapshot.`
      );
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

  const handleRouteItems = async (
    target: "memory" | "research" | "dismissed" | "unrouted",
    itemIds: string[],
    selectedMode: CodebaseMemoryIngestMode = "direct"
  ) => {
    if (!currentBank || !selectedCodebaseId || itemIds.length === 0) return;
    setRoutingTarget(target);
    try {
      const response = await client.routeCodebaseReviewItems(currentBank, selectedCodebaseId, {
        item_ids: itemIds,
        target,
        queue_memory_import: target === "memory",
        memory_ingest_mode: selectedMode,
      });
      setSelectedChunkIds([]);
      setReviewSummary((current) =>
        current
          ? {
              ...current,
              review_counts: response.review_counts,
            }
          : current
      );
      await Promise.all([
        loadSelectedCodebase(selectedCodebaseId),
        loadReviewSummary(selectedCodebaseId),
        loadChunks(selectedCodebaseId),
        loadResearchQueue(selectedCodebaseId),
      ]);
      if (response.operation_id) {
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
      }
      toast.success(
        response.queued_for_memory
          ? `Updated ${response.updated_count} chunk${response.updated_count === 1 ? "" : "s"} to memory and queued ${memoryIngestModeLabel(selectedMode).toLowerCase()} intake.`
          : `Updated ${response.updated_count} chunk${response.updated_count === 1 ? "" : "s"} to ${target}.`
      );
    } finally {
      setRoutingTarget(null);
    }
  };

  const confirmMemoryAction = async () => {
    if (!pendingMemoryAction) return;
    const selectedMode = memoryIngestMode;
    setMemoryActionDialogOpen(false);
    if (pendingMemoryAction.kind === "approve") {
      await handleApprove(selectedMode);
    } else {
      await handleRouteItems("memory", pendingMemoryAction.itemIds, selectedMode);
    }
    setPendingMemoryAction(null);
  };

  useEffect(() => {
    if (!currentBank) return;
    void loadCodebases(false);
  }, [currentBank]);

  useEffect(() => {
    if (!currentBank || !selectedCodebaseId) {
      setSelectedCodebase(null);
      setReviewSummary(null);
      setChunksResult(null);
      setResearchResult(null);
      setApprovedChunksResult(null);
      setSelectedChunkIds([]);
      setFilesResult(null);
      setSymbolsResult(null);
      setImpactResult(null);
      return;
    }

    void loadSelectedCodebase(selectedCodebaseId);
    void loadReviewSummary(selectedCodebaseId);
    void loadChunks(selectedCodebaseId);
    void loadResearchQueue(selectedCodebaseId);
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
    if (!selectedCodebaseId) {
      setChunksResult(null);
      return;
    }
    void loadChunks(selectedCodebaseId);
  }, [
    selectedCodebaseId,
    deferredChunkQuery,
    chunkRouteFilter,
    chunkChangeFilter,
    chunkKindFilter,
    chunkFileRoleFilter,
    chunkSafetyFilter,
    chunkRouteSourceFilter,
    chunkAutoReasonFilter,
    chunkMinSignificance,
    chunkOrderBy,
  ]);

  useEffect(() => {
    if (workspaceTab !== "approved") return;
    if (!selectedCodebaseId || !selectedCodebase?.approved_snapshot_id) {
      setApprovedChunksResult(null);
      return;
    }
    void loadApprovedChunks(selectedCodebaseId, selectedCodebase.approved_snapshot_id);
  }, [workspaceTab, selectedCodebaseId, selectedCodebase?.approved_snapshot_id]);

  useEffect(() => {
    if (!selectedCodebaseId) {
      setRepoMapResult(null);
      setModuleBriefsResult(null);
      return;
    }
    if (workspaceTab === "code_map") {
      if (!repoMapResult) void loadRepoMap(selectedCodebaseId);
      if (!moduleBriefsResult) void loadModuleBriefs(selectedCodebaseId);
    }
  }, [workspaceTab, selectedCodebaseId]);

  useEffect(() => {
    setRepoMapResult(null);
    setModuleBriefsResult(null);
    setIntentResult(null);
    setTriageSettings(null);
    setChunkAutoReasonFilter(null);
  }, [selectedCodebaseId]);

  useEffect(() => {
    if (!selectedCodebaseId) return;
    if (workspaceTab === "code_map" || workspaceTab === "review") {
      void loadTriageSettings(selectedCodebaseId);
    }
  }, [workspaceTab, selectedCodebaseId]);

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
            await Promise.all([
              loadSelectedCodebase(selectedCodebaseId),
              loadReviewSummary(selectedCodebaseId),
              loadChunks(selectedCodebaseId),
              loadResearchQueue(selectedCodebaseId),
              loadFiles(selectedCodebaseId),
            ]);
          }
          if (status.status === "completed") {
            toast.success(
              status.operation_type === "codebase_approve"
                ? "Selective memory hydration completed."
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

  const repoMapGroups = useMemo(() => {
    const groups = new Map<string, RepoMapGroup>();

    for (const item of filesResult?.items || []) {
      const directory = directoryFromPath(item.path);
      const existing =
        groups.get(directory) ||
        ({
          directory,
          items: [],
          totalBytes: 0,
          changedCount: 0,
          hydratedCount: 0,
        } satisfies RepoMapGroup);

      existing.items.push(item);
      existing.totalBytes += item.size_bytes;
      if (item.change_kind !== "unchanged") existing.changedCount += 1;
      if (item.document_id) existing.hydratedCount += 1;
      groups.set(directory, existing);
    }

    return Array.from(groups.values())
      .map((group) => ({
        ...group,
        items: [...group.items].sort((left, right) => left.path.localeCompare(right.path)),
      }))
      .sort((left, right) => {
        if (left.directory === "repo root") return -1;
        if (right.directory === "repo root") return 1;
        if (right.items.length !== left.items.length) return right.items.length - left.items.length;
        return left.directory.localeCompare(right.directory);
      });
  }, [filesResult]);

  const repoMapSummary = useMemo(() => {
    const items = filesResult?.items || [];
    let changedCount = 0;
    let hydratedCount = 0;
    let previewOnlyCount = 0;
    let totalBytes = 0;

    for (const item of items) {
      totalBytes += item.size_bytes;
      if (item.change_kind !== "unchanged") changedCount += 1;
      if (item.document_id) hydratedCount += 1;
      else previewOnlyCount += 1;
    }

    return {
      fileCount: items.length,
      folderCount: repoMapGroups.length,
      changedCount,
      hydratedCount,
      previewOnlyCount,
      totalBytes,
    };
  }, [filesResult, repoMapGroups]);

  const topRepoMapDirectories = useMemo(
    () => repoMapGroups.slice(0, 6).map((group) => group.directory),
    [repoMapGroups]
  );

  const totalIndexedFiles = selectedCodebase?.stats.indexed_files || 0;
  const totalFiles = selectedCodebase?.stats.total_files || 0;
  const canApproveMemory =
    reviewSummary !== null &&
    (reviewSummary.review_counts.memory || 0) > 0 &&
    selectedCodebase?.approval_status !== "parsing" &&
    Boolean(selectedCodebase?.current_snapshot_id);
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
                          setGithubRef((current) => current || parsed.ref || "");
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
                      placeholder="main (optional, auto-detect default branch)"
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
                  <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="break-words text-lg font-semibold text-foreground [overflow-wrap:anywhere]">
                        {selectedCodebase.name}
                      </div>
                      <div className="break-words text-sm text-muted-foreground [overflow-wrap:anywhere]">
                        {selectedCodebaseSource}
                      </div>
                    </div>
                    <div className="flex min-w-0 flex-wrap gap-2 lg:justify-end">
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
                    <div className="min-w-0 rounded-lg border border-border/60 bg-background/70 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Current Snapshot
                      </div>
                      <div className="mt-1 break-all font-mono text-[13px] font-medium leading-relaxed text-foreground">
                        {selectedCodebase.current_snapshot_id || "Not imported yet"}
                      </div>
                    </div>
                    <div className="min-w-0 rounded-lg border border-border/60 bg-background/70 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Commit / Ref
                      </div>
                      <div className="mt-1 break-all font-mono text-[13px] font-medium leading-relaxed text-foreground">
                        {selectedCodebase.source_commit_sha ||
                          selectedCodebase.source_ref ||
                          "Not available"}
                      </div>
                    </div>
                    <div className="min-w-0 rounded-lg border border-border/60 bg-background/70 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Approved Snapshot
                      </div>
                      <div className="mt-1 break-all font-mono text-[13px] font-medium leading-relaxed text-foreground">
                        {selectedCodebase.approved_snapshot_id || "Waiting for approval"}
                      </div>
                    </div>
                    <div className="min-w-0 rounded-lg border border-border/60 bg-background/70 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Indexed Files / Chunks
                      </div>
                      <div className="mt-1 break-words text-sm font-medium leading-relaxed text-foreground">
                        {totalIndexedFiles} of {totalFiles} files ·{" "}
                        {selectedCodebase.stats.chunk_count || 0} chunks
                      </div>
                    </div>
                    <div className="min-w-0 rounded-lg border border-border/60 bg-background/70 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Review Queue
                      </div>
                      <div className="mt-1 break-words text-sm font-medium leading-relaxed text-foreground">
                        {(reviewSummary?.review_counts.unrouted || 0).toLocaleString()} unrouted ·{" "}
                        {(reviewSummary?.review_counts.memory || 0).toLocaleString()} to memory
                      </div>
                    </div>
                    <div className="min-w-0 rounded-lg border border-border/60 bg-background/70 p-3">
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

                <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_auto_auto]">
                  <Input
                    value={refreshRef}
                    onChange={(event) => setRefreshRef(event.target.value)}
                    placeholder="Optional ref override for refresh"
                    disabled={selectedCodebase.source_type !== "github"}
                    className="min-w-0"
                  />
                  <Button
                    variant="outline"
                    onClick={handleRefresh}
                    disabled={refreshingCodebase || selectedCodebase.source_type !== "github"}
                    className="w-full xl:w-auto"
                  >
                    {refreshingCodebase ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <RefreshCw className="mr-2 h-4 w-4" />
                    )}
                    Refresh
                  </Button>
                  <Button
                    onClick={() =>
                      openMemoryActionDialog({
                        kind: "approve",
                        chunkCount: reviewSummary?.review_counts.memory || 0,
                        previewChunk: null,
                      })
                    }
                    disabled={!canApproveMemory || approvingCodebase}
                    className="w-full xl:w-auto"
                  >
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
                {!canApproveMemory &&
                  selectedCodebase.approval_status !== "parsing" &&
                  (reviewSummary?.review_counts.memory || 0) === 0 && (
                    <p className="text-xs text-muted-foreground">
                      Route one or more review chunks to memory before approving hydration.
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
            <div className="mb-4 overflow-x-auto pb-1">
              <TabsList className="inline-flex h-auto min-w-full gap-1 rounded-lg bg-muted/60 p-1">
                {(
                  [
                    {
                      value: "review",
                      label: "Review Queue",
                      icon: Inbox,
                      desc: "Triage chunks the auto-router left in the gray zone. Filter by route reason, role, safety, or significance.",
                    },
                    {
                      value: "code_map",
                      label: "Code Map",
                      icon: MapIcon,
                      desc: "Aider-style PageRank over the symbol graph plus module briefs. Best place to learn an unfamiliar repo.",
                    },
                    {
                      value: "curate",
                      label: "Curate by Intent",
                      icon: Sparkles,
                      desc: "Describe what you are about to build — get a tailored bundle of clusters and symbol cards ranked by intent.",
                    },
                    {
                      value: "files",
                      label: "Files",
                      icon: Files,
                      desc: "Browse the indexed file tree with size, language, and memory-status filters.",
                    },
                    {
                      value: "symbols",
                      label: "Symbol Search",
                      icon: Search,
                      desc: "Jump-to-symbol with exact, prefix, and fuzzy matching across the snapshot.",
                    },
                    {
                      value: "impact",
                      label: "Impact",
                      icon: Network,
                      desc: "Trace the structural blast radius for a path, symbol, or query before refactoring.",
                    },
                    {
                      value: "research",
                      label: "Research Queue",
                      icon: Telescope,
                      desc: "Chunks staged for deeper follow-up that should not be hydrated into memory yet.",
                    },
                    {
                      value: "approved",
                      label: "Approved Memory",
                      icon: CheckCircle2,
                      desc: "What is currently powering recall and reflect — the last approved snapshot's documents.",
                    },
                  ] as const
                ).map(({ value, label, icon: Icon, desc }) => (
                  <Tooltip key={value} delayDuration={250}>
                    <TooltipTrigger asChild>
                      <TabsTrigger
                        value={value}
                        className="group relative gap-1.5 px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-background/70 hover:text-foreground data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm"
                      >
                        <Icon className="h-3.5 w-3.5 opacity-70 transition-opacity group-hover:opacity-100 group-data-[state=active]:opacity-100" />
                        {label}
                      </TabsTrigger>
                    </TooltipTrigger>
                    <TooltipContent
                      side="bottom"
                      align="center"
                      className="max-w-[260px] px-3 py-2 text-xs leading-snug"
                    >
                      <div className="font-semibold">{label}</div>
                      <div className="mt-0.5 text-primary-foreground/80">{desc}</div>
                    </TooltipContent>
                  </Tooltip>
                ))}
              </TabsList>
            </div>

            <TabsContent value="review" className="space-y-4">
              <div className="grid gap-4 md:grid-cols-4">
                <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">
                    Unrouted
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-foreground">
                    {loadingReviewSummary
                      ? "..."
                      : (reviewSummary?.review_counts.unrouted || 0).toLocaleString()}
                  </div>
                </div>
                <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">
                    To Memory
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-foreground">
                    {loadingReviewSummary
                      ? "..."
                      : (reviewSummary?.review_counts.memory || 0).toLocaleString()}
                  </div>
                </div>
                <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">
                    Clusters
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-foreground">
                    {loadingReviewSummary
                      ? "..."
                      : (reviewSummary?.cluster_count || 0).toLocaleString()}
                  </div>
                </div>
                <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">
                    Related Edges
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-foreground">
                    {loadingReviewSummary
                      ? "..."
                      : (reviewSummary?.related_chunk_count || 0).toLocaleString()}
                  </div>
                </div>
              </div>

              {reviewSummary?.diagnostics?.length ? (
                <div className="rounded-xl border border-border/70 bg-muted/10 p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Auto-triage breakdown
                    </div>
                    {chunkAutoReasonFilter ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 text-xs"
                        onClick={() => setChunkAutoReasonFilter(null)}
                      >
                        Clear filter
                      </Button>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {reviewSummary.diagnostics.map((item) => {
                      const isActive = chunkAutoReasonFilter === item.reason;
                      return (
                        <button
                          key={`auto-${item.reason}-${item.count}`}
                          type="button"
                          onClick={() => setChunkAutoReasonFilter(isActive ? null : item.reason)}
                          className={`rounded-full px-3 py-1 text-xs font-medium ring-1 transition ${
                            isActive
                              ? "bg-primary/15 text-primary ring-primary/40"
                              : "bg-muted text-muted-foreground ring-border hover:bg-muted/70"
                          }`}
                          title={`Click to filter by reason: ${item.reason}`}
                        >
                          {item.reason} · {item.count.toLocaleString()}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ) : null}

              <div className="grid gap-4 xl:grid-cols-[1.2fr_0.9fr_0.8fr_0.8fr_auto]">
                <div className="space-y-2">
                  <Label htmlFor="chunk-query">Chunk Query</Label>
                  <Input
                    id="chunk-query"
                    value={chunkQuery}
                    onChange={(event) => setChunkQuery(event.target.value)}
                    placeholder="auth middleware, payment flow, render dashboard"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="chunk-route-filter">Route</Label>
                  <Select value={chunkRouteFilter} onValueChange={setChunkRouteFilter}>
                    <SelectTrigger id="chunk-route-filter">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All routes</SelectItem>
                      <SelectItem value="unrouted">Unrouted</SelectItem>
                      <SelectItem value="memory">Memory</SelectItem>
                      <SelectItem value="research">Research</SelectItem>
                      <SelectItem value="dismissed">Dismissed</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="chunk-change-filter">Change Scope</Label>
                  <Select value={chunkChangeFilter} onValueChange={setChunkChangeFilter}>
                    <SelectTrigger id="chunk-change-filter">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All chunks</SelectItem>
                      <SelectItem value="changed">Changed only</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="chunk-kind-filter">Kind</Label>
                  <Select value={chunkKindFilter} onValueChange={setChunkKindFilter}>
                    <SelectTrigger id="chunk-kind-filter">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All kinds</SelectItem>
                      <SelectItem value="function">Function</SelectItem>
                      <SelectItem value="class">Class</SelectItem>
                      <SelectItem value="interface">Interface</SelectItem>
                      <SelectItem value="type">Type</SelectItem>
                      <SelectItem value="variable">Variable</SelectItem>
                      <SelectItem value="region">Region</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end">
                  <Button
                    variant="outline"
                    disabled={!selectedCodebaseId || loadingChunks}
                    onClick={() => selectedCodebaseId && void loadChunks(selectedCodebaseId)}
                    className="w-full"
                  >
                    {loadingChunks ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Layers3 className="mr-2 h-4 w-4" />
                    )}
                    Refresh
                  </Button>
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-5">
                <div className="space-y-2">
                  <Label htmlFor="chunk-file-role-filter">File role</Label>
                  <Select value={chunkFileRoleFilter} onValueChange={setChunkFileRoleFilter}>
                    <SelectTrigger id="chunk-file-role-filter">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {FILE_ROLE_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="chunk-route-source-filter">Route source</Label>
                  <Select value={chunkRouteSourceFilter} onValueChange={setChunkRouteSourceFilter}>
                    <SelectTrigger id="chunk-route-source-filter">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ROUTE_SOURCE_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="chunk-safety-filter">Safety tag</Label>
                  <Select value={chunkSafetyFilter} onValueChange={setChunkSafetyFilter}>
                    <SelectTrigger id="chunk-safety-filter">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SAFETY_TAG_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="chunk-order-by">Order by</Label>
                  <Select
                    value={chunkOrderBy}
                    onValueChange={(value) => setChunkOrderBy(value as ChunkOrderBy)}
                  >
                    <SelectTrigger id="chunk-order-by">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">Default (recency)</SelectItem>
                      <SelectItem value="significance">Significance ↓</SelectItem>
                      <SelectItem value="complexity">Complexity ↓</SelectItem>
                      <SelectItem value="pagerank">PageRank ↓</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="chunk-min-significance">Min significance</Label>
                  <Input
                    id="chunk-min-significance"
                    type="number"
                    step="0.05"
                    min="0"
                    max="1"
                    value={chunkMinSignificance}
                    onChange={(event) => setChunkMinSignificance(event.target.value)}
                    placeholder="0.30"
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border/70 bg-muted/10 p-3">
                <Button
                  size="sm"
                  disabled={!selectedChunkIds.length || routingTarget !== null}
                  onClick={() =>
                    openMemoryActionDialog({
                      kind: "route",
                      itemIds: selectedChunkIds,
                      chunkCount: selectedChunkIds.length,
                      previewChunk:
                        selectedChunkIds.length === 1 && chunksResult
                          ? chunksResult.items.find((item) => item.id === selectedChunkIds[0]) ||
                            null
                          : null,
                    })
                  }
                >
                  {routingTarget === "memory" ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="mr-2 h-4 w-4" />
                  )}
                  Send To Memory
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!selectedChunkIds.length || routingTarget !== null}
                  onClick={() => void handleRouteItems("research", selectedChunkIds)}
                >
                  <Sparkles className="mr-2 h-4 w-4" />
                  Send To Research
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!selectedChunkIds.length || routingTarget !== null}
                  onClick={() => void handleRouteItems("dismissed", selectedChunkIds)}
                >
                  Dismiss
                </Button>
                <div className="text-sm text-muted-foreground">
                  {selectedChunkIds.length
                    ? `${selectedChunkIds.length} chunk${selectedChunkIds.length === 1 ? "" : "s"} selected`
                    : "Select chunks to bulk-route them."}
                </div>
              </div>

              {chunksResult?.items?.length ? (
                <div className="space-y-4">
                  <div className="overflow-x-auto rounded-xl border border-border/70">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-12">
                            <Checkbox
                              checked={
                                chunksResult.items.length > 0 &&
                                chunksResult.items.every((item) =>
                                  selectedChunkIds.includes(item.id)
                                )
                              }
                              onCheckedChange={(checked) =>
                                setSelectedChunkIds(
                                  checked ? chunksResult.items.map((item) => item.id) : []
                                )
                              }
                            />
                          </TableHead>
                          <TableHead>Chunk</TableHead>
                          <TableHead>Path</TableHead>
                          <TableHead>Role</TableHead>
                          <TableHead>Significance</TableHead>
                          <TableHead>Safety</TableHead>
                          <TableHead>Cluster</TableHead>
                          <TableHead>Route</TableHead>
                          <TableHead className="text-right">Actions</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {chunksResult.items.map((item) => (
                          <TableRow key={item.id}>
                            <TableCell>
                              <Checkbox
                                checked={selectedChunkIds.includes(item.id)}
                                onCheckedChange={(checked) =>
                                  setSelectedChunkIds((current) =>
                                    checked
                                      ? [...current, item.id]
                                      : current.filter((value) => value !== item.id)
                                  )
                                }
                              />
                            </TableCell>
                            <TableCell>
                              <div className="min-w-[220px]">
                                <div className="font-medium text-card-foreground">{item.label}</div>
                                <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                  {item.preview_text}
                                </div>
                              </div>
                            </TableCell>
                            <TableCell className="max-w-[22rem]">
                              <HoverPath
                                value={`${item.path}:${item.start_line}-${item.end_line}`}
                              />
                              <div className="mt-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                                {item.kind}
                                {item.change_kind && item.change_kind !== "unchanged"
                                  ? ` · ${item.change_kind}`
                                  : ""}
                              </div>
                            </TableCell>
                            <TableCell>
                              {item.file_role ? (
                                <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground ring-1 ring-border">
                                  {item.file_role.replace(/_/g, " ")}
                                </span>
                              ) : (
                                <span className="text-xs text-muted-foreground">—</span>
                              )}
                            </TableCell>
                            <TableCell>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span
                                    className={`text-sm tabular-nums cursor-help ${significanceTone(item.significance_score)}`}
                                  >
                                    {formatSignificance(item.significance_score)}
                                  </span>
                                </TooltipTrigger>
                                <TooltipContent side="top" className="max-w-sm text-xs">
                                  <div className="font-semibold mb-1">Significance components</div>
                                  {item.significance_components ? (
                                    <ul className="space-y-0.5">
                                      {Object.entries(item.significance_components)
                                        .filter(([, v]) => typeof v === "number")
                                        .sort(([, a], [, b]) => (Number(b) || 0) - (Number(a) || 0))
                                        .slice(0, 8)
                                        .map(([key, value]) => (
                                          <li key={key} className="flex justify-between gap-3">
                                            <span className="text-muted-foreground">
                                              {key.replace(/_/g, " ")}
                                            </span>
                                            <span className="tabular-nums">
                                              {(Number(value) || 0).toFixed(2)}
                                            </span>
                                          </li>
                                        ))}
                                    </ul>
                                  ) : (
                                    <span className="text-muted-foreground">
                                      No score available yet.
                                    </span>
                                  )}
                                  {item.complexity_score !== null &&
                                  item.complexity_score !== undefined ? (
                                    <div className="mt-2 text-muted-foreground">
                                      Complexity density: {item.complexity_score.toFixed(2)}
                                    </div>
                                  ) : null}
                                  {item.pagerank_centrality ? (
                                    <div className="text-muted-foreground">
                                      PageRank: {item.pagerank_centrality.toFixed(4)} · fan-in{" "}
                                      {item.fanin_count ?? 0}
                                    </div>
                                  ) : null}
                                </TooltipContent>
                              </Tooltip>
                            </TableCell>
                            <TableCell>
                              <div className="flex flex-wrap gap-1">
                                {(item.safety_tags || []).length === 0 ? (
                                  <span className="text-xs text-muted-foreground">—</span>
                                ) : (
                                  (item.safety_tags || []).slice(0, 3).map((tag) => (
                                    <span
                                      key={tag}
                                      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${safetyTagTone(tag)}`}
                                    >
                                      {tag}
                                    </span>
                                  ))
                                )}
                              </div>
                            </TableCell>
                            <TableCell className="text-card-foreground">
                              {item.cluster_label || "-"}
                            </TableCell>
                            <TableCell>
                              <div className="flex flex-col gap-1">
                                <span
                                  className={`w-fit rounded-full px-2.5 py-1 text-xs font-semibold ${routeTone(item.route_target)}`}
                                >
                                  {formatStatusLabel(item.route_target)}
                                </span>
                                {item.route_source ? (
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <span
                                        className={`w-fit cursor-help rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${routeSourceTone(item.route_source)}`}
                                      >
                                        {formatRouteSource(item.route_source)}
                                      </span>
                                    </TooltipTrigger>
                                    <TooltipContent side="top" className="max-w-xs text-xs">
                                      <div className="font-semibold">Why this route?</div>
                                      <div className="mt-1 text-muted-foreground">
                                        {item.auto_route_reason || "Manual decision."}
                                      </div>
                                    </TooltipContent>
                                  </Tooltip>
                                ) : null}
                              </div>
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="flex justify-end gap-2">
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={() => void openChunkDetail(item.id)}
                                    >
                                      Details
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent side="top">
                                    Inspect code, symbols, related chunks, and impact edges.
                                  </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      onClick={() =>
                                        openMemoryActionDialog({
                                          kind: "route",
                                          itemIds: [item.id],
                                          chunkCount: 1,
                                          previewChunk: item,
                                        })
                                      }
                                      disabled={routingTarget !== null}
                                    >
                                      Memory
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent side="top">
                                    Route this chunk into approved memory on the next apply step.
                                  </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      onClick={() => void handleRouteItems("research", [item.id])}
                                      disabled={routingTarget !== null}
                                    >
                                      Research
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent side="top">
                                    Keep this chunk staged for deeper review without memory
                                    hydration.
                                  </TooltipContent>
                                </Tooltip>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>

                  {chunksResult.has_more && (
                    <div className="flex justify-center">
                      <Button
                        variant="outline"
                        onClick={() =>
                          selectedCodebaseId &&
                          void loadChunks(selectedCodebaseId, chunksResult.next_cursor, true)
                        }
                        disabled={loadingChunks}
                      >
                        {loadingChunks ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <ChevronsRight className="mr-2 h-4 w-4" />
                        )}
                        Load More Chunks
                      </Button>
                    </div>
                  )}

                  {reviewSummary?.diagnostics?.length ? (
                    <div className="rounded-xl border border-border/70 p-4">
                      <div className="mb-3 text-sm font-semibold text-foreground">
                        Review Diagnostics
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {reviewSummary.diagnostics.map((item) => (
                          <span
                            key={`${item.reason}-${item.count}`}
                            className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground"
                          >
                            {item.reason} · {item.count}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                  {selectedCodebaseId
                    ? "The review queue will show semantic chunks once the current snapshot has been parsed."
                    : "Select a codebase to load the review queue."}
                </div>
              )}
            </TabsContent>

            <TabsContent value="code_map" className="space-y-5">
              <div className="flex flex-wrap items-start gap-3 rounded-xl border border-border/70 bg-gradient-to-br from-muted/30 to-transparent p-4">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <div className="rounded-lg bg-primary/10 p-2 text-primary">
                    <MapIcon className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <h3 className="text-sm font-semibold text-foreground">
                        Repo Map &amp; Module Briefs
                      </h3>
                      <Tooltip delayDuration={200}>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                          >
                            <HelpCircle className="h-3.5 w-3.5" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="max-w-[300px] text-xs leading-snug">
                          Symbols are ranked by Aider-style PageRank over the call/import graph.
                          Module briefs summarize each folder's role, public surface, and
                          dependencies. Both refresh on every index pass.
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Generated deterministically when the snapshot is indexed. Use this to learn an
                      unfamiliar repo or pick refactor targets.
                    </p>
                  </div>
                </div>
                <div className="flex flex-shrink-0 items-center gap-2">
                  <Tooltip delayDuration={200}>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!selectedCodebaseId || loadingRepoMap}
                        onClick={() => selectedCodebaseId && void loadRepoMap(selectedCodebaseId)}
                      >
                        {loadingRepoMap ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <RefreshCw className="mr-2 h-4 w-4" />
                        )}
                        Repo map
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" className="max-w-[240px] text-xs">
                      Re-fetch the cached PageRank table for this snapshot.
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={200}>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!selectedCodebaseId || loadingModuleBriefs}
                        onClick={() =>
                          selectedCodebaseId && void loadModuleBriefs(selectedCodebaseId)
                        }
                      >
                        {loadingModuleBriefs ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <RefreshCw className="mr-2 h-4 w-4" />
                        )}
                        Modules
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" className="max-w-[240px] text-xs">
                      Re-fetch the per-folder module briefs.
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={200}>
                    <TooltipTrigger asChild>
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={!selectedCodebaseId || loadingTriageSettings}
                        onClick={openTriageSettingsDialog}
                      >
                        <Sliders className="mr-2 h-4 w-4" />
                        Tune triage
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" className="max-w-[280px] text-xs">
                      Adjust auto-triage thresholds, embedding provider, and safety scanning. New
                      settings apply on the next index pass.
                    </TooltipContent>
                  </Tooltip>
                </div>
              </div>

              {triageSettings ? (
                <div className="grid gap-2 rounded-xl border border-border/70 bg-muted/10 p-3 text-xs sm:grid-cols-3 lg:grid-cols-5">
                  {(
                    [
                      {
                        label: "Embedding",
                        value: triageSettings.embedding_provider,
                        tip: "Code-aware embedding model used by Curate by Intent. jina_local runs on the host; voyage_code_3 calls a paid API.",
                      },
                      {
                        label: "High threshold",
                        value: triageSettings.score_threshold_high.toFixed(2),
                        tip: "Significance score (0..1) at which a chunk auto-routes to memory. Lower = more chunks promoted, higher = tighter gold layer.",
                      },
                      {
                        label: "Centrality",
                        value: triageSettings.centrality_threshold.toFixed(2),
                        tip: "PageRank cutoff for pulling structurally connected symbols into the review queue when their score is mid.",
                      },
                      {
                        label: "Safety scan",
                        value: triageSettings.enable_safety_scan
                          ? triageSettings.enable_semgrep
                            ? "On + Semgrep"
                            : "On"
                          : "Off",
                        tip: "Built-in regex scanner tags auth, crypto, SQL, eval, deserialization, subprocess, network. Semgrep adds CI-grade rules (heavier).",
                      },
                      {
                        label: "SCIP",
                        value: triageSettings.scip_index_path ? "Configured" : "Off",
                        tip: "Optional path to a precomputed SCIP index for precise cross-references. Falls back to tree-sitter heuristics when off.",
                      },
                    ] as const
                  ).map((item) => (
                    <Tooltip key={item.label} delayDuration={200}>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          className="flex w-full flex-col items-start rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <div className="flex items-center gap-1 uppercase tracking-wide text-muted-foreground">
                            {item.label}
                            <Info className="h-3 w-3 opacity-50" />
                          </div>
                          <div className="mt-0.5 font-medium text-foreground">{item.value}</div>
                        </button>
                      </TooltipTrigger>
                      <TooltipContent
                        side="bottom"
                        align="start"
                        className="max-w-[280px] text-xs leading-snug"
                      >
                        {item.tip}
                      </TooltipContent>
                    </Tooltip>
                  ))}
                </div>
              ) : null}

              <div className="grid gap-4 xl:grid-cols-2">
                <div className="rounded-xl border border-border/70 bg-card shadow-sm">
                  <div className="flex items-center justify-between border-b border-border/60 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Zap className="h-4 w-4 text-primary" />
                      <div className="text-sm font-semibold text-foreground">
                        Top symbols by PageRank
                      </div>
                      <Tooltip delayDuration={200}>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                          >
                            <HelpCircle className="h-3.5 w-3.5" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="max-w-[280px] text-xs leading-snug">
                          Symbols sorted by their PageRank centrality on the call/import graph. High
                          fan-in usually means it's a good first read for new contributors.
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <div className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                      {repoMapResult?.repo_map?.top_symbols?.length || 0} ranked
                    </div>
                  </div>
                  <div className="p-4">
                    {loadingRepoMap ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Loading repo map...
                      </div>
                    ) : repoMapResult?.repo_map?.top_symbols?.length ? (
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Symbol</TableHead>
                              <TableHead>Path</TableHead>
                              <TableHead className="text-right">PageRank</TableHead>
                              <TableHead className="text-right">Fan-in</TableHead>
                              <TableHead>Safety</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {repoMapResult.repo_map.top_symbols.slice(0, 50).map((symbol) => (
                              <TableRow key={`${symbol.path}::${symbol.fq_name}`}>
                                <TableCell>
                                  <div className="font-medium text-card-foreground">
                                    {symbol.name}
                                  </div>
                                  <div className="text-[11px] text-muted-foreground">
                                    {symbol.kind}
                                    {symbol.language ? ` · ${symbol.language}` : ""}
                                  </div>
                                </TableCell>
                                <TableCell className="max-w-[18rem]">
                                  <HoverPath value={`${symbol.path}:${symbol.start_line}`} />
                                </TableCell>
                                <TableCell className="text-right tabular-nums text-card-foreground">
                                  {symbol.pagerank.toFixed(4)}
                                </TableCell>
                                <TableCell className="text-right tabular-nums text-card-foreground">
                                  {symbol.fanin}
                                </TableCell>
                                <TableCell>
                                  <div className="flex flex-wrap gap-1">
                                    {(symbol.safety_tags || []).slice(0, 3).map((tag) => (
                                      <span
                                        key={tag}
                                        className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${safetyTagTone(tag)}`}
                                      >
                                        {tag}
                                      </span>
                                    ))}
                                  </div>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    ) : (
                      <div className="rounded-lg border border-dashed border-border/70 bg-muted/10 p-6 text-center text-sm text-muted-foreground">
                        <MapIcon className="mx-auto mb-2 h-6 w-6 opacity-40" />
                        {selectedCodebaseId
                          ? "Repo map is generated when a snapshot is indexed. Re-index to populate."
                          : "Select a codebase to view its repo map."}
                      </div>
                    )}
                  </div>
                </div>

                <div className="rounded-xl border border-border/70 bg-card shadow-sm">
                  <div className="flex items-center justify-between border-b border-border/60 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Boxes className="h-4 w-4 text-primary" />
                      <div className="text-sm font-semibold text-foreground">Module briefs</div>
                      <Tooltip delayDuration={200}>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                          >
                            <HelpCircle className="h-3.5 w-3.5" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="max-w-[280px] text-xs leading-snug">
                          Per-folder summaries: dominant role, public surface, top symbols, and
                          internal dependencies. Great for picking the right module to dive into.
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <div className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                      {moduleBriefsResult?.items?.length || 0} modules
                    </div>
                  </div>
                  <div className="p-4">
                    {loadingModuleBriefs ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Loading modules...
                      </div>
                    ) : moduleBriefsResult?.items?.length ? (
                      <div className="space-y-3 max-h-[640px] overflow-y-auto pr-1">
                        {moduleBriefsResult.items.map((brief) => (
                          <div
                            key={brief.module}
                            className="rounded-lg border border-border/70 bg-muted/10 p-3"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="font-medium text-card-foreground">{brief.module}</div>
                              <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                                <span>{brief.file_count} files</span>
                                {brief.dominant_language ? (
                                  <span>· {brief.dominant_language}</span>
                                ) : null}
                                {brief.dominant_role ? (
                                  <span className="rounded-full bg-muted px-2 py-0.5 ring-1 ring-border">
                                    {brief.dominant_role.replace(/_/g, " ")}
                                  </span>
                                ) : null}
                              </div>
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {brief.purpose}
                            </div>
                            {brief.public_surface?.length ? (
                              <div className="mt-2 text-[11px] text-muted-foreground">
                                <span className="font-semibold uppercase tracking-wide">
                                  Public surface:
                                </span>{" "}
                                {brief.public_surface.slice(0, 6).join(", ")}
                              </div>
                            ) : null}
                            {brief.top_symbols?.length ? (
                              <div className="mt-1 text-[11px] text-muted-foreground">
                                <span className="font-semibold uppercase tracking-wide">
                                  Top symbols:
                                </span>{" "}
                                {brief.top_symbols.slice(0, 6).join(", ")}
                              </div>
                            ) : null}
                            {brief.internal_dependencies?.length ? (
                              <div className="mt-1 text-[11px] text-muted-foreground">
                                <span className="font-semibold uppercase tracking-wide">
                                  Depends on:
                                </span>{" "}
                                {brief.internal_dependencies.slice(0, 5).join(", ")}
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="rounded-lg border border-dashed border-border/70 bg-muted/10 p-6 text-center text-sm text-muted-foreground">
                        <Boxes className="mx-auto mb-2 h-6 w-6 opacity-40" />
                        {selectedCodebaseId
                          ? "Module briefs appear after the next index pass with the code-intel pipeline enabled."
                          : "Select a codebase to view its module briefs."}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </TabsContent>

            <TabsContent value="curate" className="space-y-5">
              <div className="rounded-xl border border-border/70 bg-gradient-to-br from-muted/30 to-transparent p-4">
                <div className="flex items-start gap-3">
                  <div className="rounded-lg bg-primary/10 p-2 text-primary">
                    <Sparkles className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <h3 className="text-sm font-semibold text-foreground">Curate by intent</h3>
                      <Tooltip delayDuration={200}>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                          >
                            <HelpCircle className="h-3.5 w-3.5" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="max-w-[300px] text-xs leading-snug">
                          We embed your intent with a code-aware model and re-rank chunks using
                          cosine similarity, token overlap, optional path scope, and the chunk's
                          significance score. Each result explains why it ranked.
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Describe the work you&apos;re about to do. We&apos;ll reduce the snapshot to
                      the smallest useful slice — clusters and symbol cards — that you can route
                      straight to memory.
                    </p>
                  </div>
                </div>

                <div className="mt-4 grid gap-3 lg:grid-cols-[1.2fr_0.8fr_auto]">
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor="intent-input">Intent</Label>
                      <Tooltip delayDuration={200}>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                          >
                            <HelpCircle className="h-3 w-3" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-[260px] text-xs leading-snug">
                          A short natural-language sentence. The more specific, the tighter the
                          curated bundle.
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <Input
                      id="intent-input"
                      value={intentInput}
                      onChange={(event) => setIntentInput(event.target.value)}
                      placeholder="Add idempotency keys to checkout API; fix race in payment retries"
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && intentInput.trim()) {
                          event.preventDefault();
                          void runIntentCuration();
                        }
                      }}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor="intent-scope-hint">Scope hint (optional)</Label>
                      <Tooltip delayDuration={200}>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                          >
                            <HelpCircle className="h-3 w-3" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-[260px] text-xs leading-snug">
                          Comma-separated path prefixes. Results matching these paths get a ranking
                          boost — leave blank to search the whole repo.
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <Input
                      id="intent-scope-hint"
                      value={intentScopeHint}
                      onChange={(event) => setIntentScopeHint(event.target.value)}
                      placeholder="services/payments, src/api"
                    />
                  </div>
                  <div className="flex items-end">
                    <Tooltip delayDuration={200}>
                      <TooltipTrigger asChild>
                        <Button
                          disabled={!selectedCodebaseId || loadingIntent || !intentInput.trim()}
                          onClick={() => void runIntentCuration()}
                          className="w-full"
                        >
                          {loadingIntent ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : (
                            <Sparkles className="mr-2 h-4 w-4" />
                          )}
                          Curate
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent side="bottom" className="max-w-[240px] text-xs">
                        Press Enter inside the intent box for the same shortcut.
                      </TooltipContent>
                    </Tooltip>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    Try
                  </span>
                  {[
                    "Where do we authenticate API requests",
                    "Find rate limiting middleware",
                    "Database migration patterns",
                    "How embeddings are cached",
                  ].map((example) => (
                    <button
                      key={example}
                      type="button"
                      onClick={() => setIntentInput(example)}
                      className="rounded-full border border-border/70 bg-card px-2.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-foreground"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>

              {intentResult ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="rounded-full bg-muted px-2 py-0.5">
                      {intentResult.total_candidates.toLocaleString()} candidate
                      {intentResult.total_candidates === 1 ? "" : "s"} ranked
                    </span>
                    <span className="rounded-full bg-muted px-2 py-0.5">
                      {intentResult.clusters.length} cluster
                      {intentResult.clusters.length === 1 ? "" : "s"}
                    </span>
                    <span className="rounded-full bg-muted px-2 py-0.5">
                      {intentResult.symbol_cards.length} symbol card
                      {intentResult.symbol_cards.length === 1 ? "" : "s"}
                    </span>
                  </div>

                  {intentResult.symbol_cards.length ? (
                    <div className="rounded-xl border border-border/70 bg-card shadow-sm">
                      <div className="flex items-center gap-2 border-b border-border/60 px-4 py-3">
                        <Zap className="h-4 w-4 text-primary" />
                        <div className="text-sm font-semibold text-foreground">
                          Top symbol cards
                        </div>
                        <Tooltip delayDuration={200}>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                            >
                              <HelpCircle className="h-3.5 w-3.5" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent
                            side="right"
                            className="max-w-[280px] text-xs leading-snug"
                          >
                            High-significance symbols that best match your intent. Each card is
                            ready to be sent to memory directly.
                          </TooltipContent>
                        </Tooltip>
                      </div>
                      <div className="p-4">
                        <div className="grid gap-3 md:grid-cols-2">
                          {intentResult.symbol_cards.slice(0, 12).map((card) => (
                            <div
                              key={`${card.path}::${card.fq_name}`}
                              className="group rounded-lg border border-border/70 bg-muted/10 p-3 transition-all hover:border-primary/40 hover:bg-muted/20 hover:shadow-sm"
                            >
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0 flex-1">
                                  <div className="truncate font-medium text-card-foreground">
                                    {card.name}
                                  </div>
                                  <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                                    {card.kind}
                                    {card.language ? ` · ${card.language}` : ""} · {card.path}:
                                    {card.start_line}
                                  </div>
                                </div>
                                <Tooltip delayDuration={200}>
                                  <TooltipTrigger asChild>
                                    <div className="flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium tabular-nums text-primary">
                                      <Zap className="h-3 w-3" />
                                      {(card.intent_score ?? 0).toFixed(2)}
                                    </div>
                                  </TooltipTrigger>
                                  <TooltipContent side="left" className="max-w-[220px] text-xs">
                                    Intent rank score (0..1). Combines embedding similarity, token
                                    overlap, path match, and significance prior.
                                  </TooltipContent>
                                </Tooltip>
                              </div>
                              {card.signature ? (
                                <pre className="mt-2 overflow-x-auto rounded bg-muted/40 p-2 text-[11px] text-card-foreground">
                                  {card.signature}
                                </pre>
                              ) : null}
                              {card.purpose ? (
                                <div className="mt-2 text-xs text-muted-foreground">
                                  {card.purpose}
                                </div>
                              ) : null}
                              {(card.safety_tags || []).length ? (
                                <div className="mt-2 flex flex-wrap gap-1">
                                  {card.safety_tags.map((tag) => (
                                    <Tooltip key={tag} delayDuration={200}>
                                      <TooltipTrigger asChild>
                                        <span
                                          className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${safetyTagTone(tag)}`}
                                        >
                                          <ShieldCheck className="h-3 w-3" />
                                          {tag}
                                        </span>
                                      </TooltipTrigger>
                                      <TooltipContent side="top" className="max-w-[240px] text-xs">
                                        Detected safety pattern. Auto-routed to review (never
                                        auto-promoted) so a human can confirm intent.
                                      </TooltipContent>
                                    </Tooltip>
                                  ))}
                                </div>
                              ) : null}
                              {card.explain ? (
                                <div className="mt-2 rounded bg-muted/30 px-2 py-1 text-[11px] italic text-muted-foreground">
                                  {card.explain}
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : null}

                  {intentResult.clusters.length ? (
                    <div className="rounded-xl border border-border/70 bg-card shadow-sm">
                      <div className="flex items-center gap-2 border-b border-border/60 px-4 py-3">
                        <Layers3 className="h-4 w-4 text-primary" />
                        <div className="text-sm font-semibold text-foreground">Top clusters</div>
                        <Tooltip delayDuration={200}>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                            >
                              <HelpCircle className="h-3.5 w-3.5" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent
                            side="right"
                            className="max-w-[280px] text-xs leading-snug"
                          >
                            Groups of near-duplicate chunks. Routing the cluster sends every member
                            at once, which is the fastest way to absorb a feature.
                          </TooltipContent>
                        </Tooltip>
                      </div>
                      <div className="space-y-3 p-4">
                        {intentResult.clusters.map((cluster) => {
                          const clusterChunkIds = cluster.chunks.map((c) => c.id);
                          return (
                            <div
                              key={cluster.cluster_id}
                              className="group rounded-lg border border-border/70 bg-muted/10 p-3 transition-colors hover:border-primary/40 hover:bg-muted/20"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="min-w-0 flex-1">
                                  <div className="truncate font-medium text-card-foreground">
                                    {cluster.cluster_label || cluster.cluster_id}
                                  </div>
                                  <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                                    <span className="rounded-full bg-muted px-2 py-0.5">
                                      {cluster.size} chunk{cluster.size === 1 ? "" : "s"}
                                    </span>
                                    <span className="flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 font-medium text-primary">
                                      <Zap className="h-3 w-3" />
                                      {cluster.score.toFixed(2)}
                                    </span>
                                  </div>
                                </div>
                                <Tooltip delayDuration={200}>
                                  <TooltipTrigger asChild>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      className="h-7 gap-1"
                                      disabled={routingTarget !== null}
                                      onClick={() =>
                                        void handleRouteItems("memory", clusterChunkIds)
                                      }
                                    >
                                      <ArrowRight className="h-3.5 w-3.5" />
                                      Route to memory
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent side="left" className="max-w-[260px] text-xs">
                                    Sends every chunk in this cluster to the memory queue. Approve
                                    later via ASD Direct or Retain Pipeline.
                                  </TooltipContent>
                                </Tooltip>
                              </div>
                              <div className="mt-2 grid gap-1 text-xs">
                                {cluster.chunks.slice(0, 6).map((chunk) => (
                                  <button
                                    key={chunk.id}
                                    type="button"
                                    onClick={() => void openChunkDetail(chunk.id)}
                                    className="flex flex-wrap items-center justify-between gap-2 rounded border border-border/40 bg-card/40 px-2 py-1 text-left transition-colors hover:border-primary/40 hover:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                  >
                                    <div className="min-w-0 flex-1">
                                      <div className="truncate font-medium text-card-foreground">
                                        {chunk.label}
                                      </div>
                                      <div className="truncate text-[11px] text-muted-foreground">
                                        {chunk.path}:{chunk.start_line}-{chunk.end_line}
                                      </div>
                                    </div>
                                    <div className="text-[11px] tabular-nums text-muted-foreground">
                                      {(chunk.intent_score ?? 0).toFixed(2)}
                                    </div>
                                  </button>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ) : null}

                  {intentResult.unclustered.length ? (
                    <div className="rounded-xl border border-border/70 bg-card shadow-sm">
                      <div className="flex items-center gap-2 border-b border-border/60 px-4 py-3">
                        <Inbox className="h-4 w-4 text-muted-foreground" />
                        <div className="text-sm font-semibold text-foreground">
                          Other candidates
                        </div>
                        <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                          {intentResult.unclustered.length}
                        </span>
                      </div>
                      <div className="grid gap-1 p-4 text-xs">
                        {intentResult.unclustered.slice(0, 12).map((chunk) => (
                          <div
                            key={chunk.id}
                            className="flex flex-wrap items-center justify-between gap-2 rounded border border-border/40 bg-muted/10 px-2 py-1.5 transition-colors hover:border-primary/40 hover:bg-muted/20"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="truncate font-medium text-card-foreground">
                                {chunk.label}
                              </div>
                              <div className="truncate text-[11px] text-muted-foreground">
                                {chunk.path}:{chunk.start_line}-{chunk.end_line}
                              </div>
                            </div>
                            <div className="flex items-center gap-2 text-[11px] tabular-nums text-muted-foreground">
                              {(chunk.intent_score ?? 0).toFixed(2)}
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-6 px-2"
                                onClick={() => void openChunkDetail(chunk.id)}
                              >
                                Details
                                <ChevronRight className="ml-0.5 h-3 w-3" />
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-border/70 bg-muted/5 p-8 text-center">
                  <Sparkles className="mx-auto mb-3 h-8 w-8 text-primary/40" />
                  <div className="text-sm font-medium text-foreground">
                    Describe an intent to start curating
                  </div>
                  <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
                    The ranker uses a code-aware embedding model plus path overlap and chunk
                    significance to surface the smallest useful slice — usually 5-15 symbols instead
                    of 50,000 chunks.
                  </p>
                </div>
              )}
            </TabsContent>

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
                <div className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                    <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Visible Files
                      </div>
                      <div className="mt-2 text-2xl font-semibold text-foreground">
                        {repoMapSummary.fileCount.toLocaleString()}
                      </div>
                    </div>
                    <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Active Folders
                      </div>
                      <div className="mt-2 text-2xl font-semibold text-foreground">
                        {repoMapSummary.folderCount.toLocaleString()}
                      </div>
                    </div>
                    <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Changed Scope
                      </div>
                      <div className="mt-2 text-2xl font-semibold text-foreground">
                        {repoMapSummary.changedCount.toLocaleString()}
                      </div>
                    </div>
                    <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        In Memory
                      </div>
                      <div className="mt-2 text-2xl font-semibold text-foreground">
                        {repoMapSummary.hydratedCount.toLocaleString()}
                      </div>
                    </div>
                    <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Visible Size
                      </div>
                      <div className="mt-2 text-2xl font-semibold text-foreground">
                        {formatBytes(repoMapSummary.totalBytes)}
                      </div>
                    </div>
                  </div>

                  <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                    <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                      <div>
                        <div className="text-sm font-semibold text-foreground">Explorer View</div>
                        <div className="text-sm text-muted-foreground">
                          Grouped by folder so developers can scan real repo boundaries instead of
                          reading one long flat table.
                        </div>
                      </div>
                      <div className="text-sm text-muted-foreground">
                        {repoMapSummary.previewOnlyCount.toLocaleString()} preview-only file
                        {repoMapSummary.previewOnlyCount === 1 ? "" : "s"} waiting for memory
                        hydration
                      </div>
                    </div>
                    {topRepoMapDirectories.length ? (
                      <div className="mt-4 flex flex-wrap gap-2">
                        {topRepoMapDirectories.map((directory) => (
                          <span
                            key={directory}
                            className="rounded-full border border-border/70 bg-background/70 px-3 py-1 text-xs font-medium text-muted-foreground"
                          >
                            {directory}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  <div className="space-y-3">
                    {repoMapGroups.map((group, index) => (
                      <details
                        key={group.directory}
                        className="group overflow-hidden rounded-xl border border-border/70 bg-background/40"
                        open={index < 4}
                      >
                        <summary className="flex cursor-pointer list-none flex-col gap-3 p-4 transition-colors hover:bg-muted/10 md:flex-row md:items-start md:justify-between">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                              <ChevronRight className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90" />
                              <FolderGit2 className="h-4 w-4 shrink-0 text-primary" />
                              <span className="break-words [overflow-wrap:anywhere]">
                                {group.directory}
                              </span>
                            </div>
                            <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                              <span>{group.items.length.toLocaleString()} files</span>
                              <span>{formatBytes(group.totalBytes)}</span>
                              <span>{group.changedCount.toLocaleString()} changed</span>
                              <span>{group.hydratedCount.toLocaleString()} in memory</span>
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-2 md:justify-end">
                            <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                              {group.items.filter((item) => item.language).length} typed
                            </span>
                            <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                              {group.items.reduce((sum, item) => sum + item.chunk_count, 0)} chunks
                            </span>
                          </div>
                        </summary>

                        <div className="border-t border-border/60">
                          {group.items.map((item) => (
                            <div
                              key={`${item.path}-${item.content_hash}`}
                              className="flex flex-col gap-3 border-b border-border/50 p-4 last:border-b-0 xl:flex-row xl:items-start xl:justify-between"
                            >
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                  <div className="flex min-w-0 items-center gap-2">
                                    <Files className="h-4 w-4 shrink-0 text-muted-foreground" />
                                    <span className="break-all font-mono text-sm font-medium text-card-foreground">
                                      {fileNameFromPath(item.path)}
                                    </span>
                                  </div>
                                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                                    {item.language || "unknown"}
                                  </span>
                                </div>
                                <div className="mt-2 break-all font-mono text-xs text-muted-foreground">
                                  {item.path}
                                </div>
                                {item.reason ? (
                                  <div className="mt-2 text-xs text-muted-foreground">
                                    Reason: {item.reason}
                                  </div>
                                ) : null}
                              </div>

                              <div className="flex flex-wrap items-center gap-2 xl:max-w-[52%] xl:justify-end">
                                <span
                                  className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusClasses(item.status)}`}
                                >
                                  {formatStatusLabel(item.status)}
                                </span>
                                <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                                  {formatStatusLabel(item.change_kind)}
                                </span>
                                <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                                  {item.chunk_count} chunk{item.chunk_count === 1 ? "" : "s"}
                                </span>
                                <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                                  {formatBytes(item.size_bytes)}
                                </span>
                                <span className="break-all rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                                  {documentStateLabel(item, selectedCodebase)}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </details>
                    ))}
                  </div>
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
                        <TableHead>Chunks</TableHead>
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
                          <TableCell className="max-w-[24rem]">
                            <HoverPath value={item.path} />
                          </TableCell>
                          <TableCell className="text-card-foreground">
                            {item.container || "-"}
                          </TableCell>
                          <TableCell className="text-card-foreground">
                            {item.start_line}-{item.end_line}
                          </TableCell>
                          <TableCell className="text-card-foreground">
                            {item.chunk_ids.length}
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
                              <TableHead>Chunks</TableHead>
                              <TableHead>Status</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {impactResult.impacted_files.map((item) => (
                              <TableRow key={`${item.path}-${item.depth}`}>
                                <TableCell className="max-w-[24rem]">
                                  <HoverPath value={item.path} />
                                </TableCell>
                                <TableCell className="text-card-foreground">{item.depth}</TableCell>
                                <TableCell className="text-card-foreground">
                                  {item.chunk_count}
                                </TableCell>
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
                              <div className="break-all font-mono text-xs text-foreground">
                                {edge.from_path}
                              </div>
                              <div className="my-1 text-xs uppercase tracking-wide text-muted-foreground">
                                {edge.edge_type}
                              </div>
                              <div className="break-all font-mono text-xs text-foreground">
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

            <TabsContent value="research" className="space-y-4">
              <div className="rounded-xl border border-border/70 bg-muted/10 p-4 text-sm text-muted-foreground">
                Research Queue keeps mechanically-related chunks staged for deeper developer review
                without hydrating them into memory.
              </div>

              {researchResult?.items?.length ? (
                <div className="space-y-4">
                  <div className="overflow-x-auto rounded-xl border border-border/70">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Chunk</TableHead>
                          <TableHead>Path</TableHead>
                          <TableHead>Cluster</TableHead>
                          <TableHead>Related</TableHead>
                          <TableHead className="text-right">Actions</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {researchResult.items.map((item) => (
                          <TableRow key={item.id}>
                            <TableCell>
                              <div className="font-medium text-card-foreground">{item.label}</div>
                              <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                {item.preview_text}
                              </div>
                            </TableCell>
                            <TableCell className="max-w-[22rem]">
                              <HoverPath
                                value={`${item.path}:${item.start_line}-${item.end_line}`}
                              />
                            </TableCell>
                            <TableCell className="text-card-foreground">
                              {item.cluster_label || "-"}
                            </TableCell>
                            <TableCell className="text-card-foreground">
                              {item.related_count}
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="flex justify-end gap-2">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => void openChunkDetail(item.id)}
                                >
                                  Details
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() =>
                                    openMemoryActionDialog({
                                      kind: "route",
                                      itemIds: [item.id],
                                      chunkCount: 1,
                                      previewChunk: item,
                                    })
                                  }
                                >
                                  Promote To Memory
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>

                  {researchResult.has_more && (
                    <div className="flex justify-center">
                      <Button
                        variant="outline"
                        onClick={() =>
                          selectedCodebaseId &&
                          void loadResearchQueue(
                            selectedCodebaseId,
                            researchResult.next_cursor,
                            true
                          )
                        }
                        disabled={loadingResearch}
                      >
                        {loadingResearch ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Network className="mr-2 h-4 w-4" />
                        )}
                        Load More Research
                      </Button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                  Route chunks to research when you want them staged for follow-up without hydrating
                  them into memory yet.
                </div>
              )}
            </TabsContent>

            <TabsContent value="approved" className="space-y-4">
              {selectedCodebase?.approved_snapshot_id ? (
                <>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Approved Snapshot
                      </div>
                      <div className="mt-2 break-all font-mono text-sm font-semibold text-foreground">
                        {selectedCodebase.approved_snapshot_id}
                      </div>
                    </div>
                    <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Approved Source
                      </div>
                      <div className="mt-2 break-all font-mono text-sm font-semibold text-foreground">
                        {selectedCodebase.approved_source_commit_sha ||
                          selectedCodebase.approved_source_ref ||
                          "Not available"}
                      </div>
                    </div>
                    <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Loaded Chunks
                      </div>
                      <div className="mt-2 text-2xl font-semibold text-foreground">
                        {(approvedChunksResult?.items.length || 0).toLocaleString()}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        Current page of memory-backed chunk history
                      </div>
                    </div>
                    <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Approved Updated
                      </div>
                      <div className="mt-2 text-sm font-semibold text-foreground">
                        {formatRelative(
                          selectedCodebase.approved_snapshot_updated_at ||
                            selectedCodebase.updated_at
                        )}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {formatDateTime(
                          selectedCodebase.approved_snapshot_updated_at ||
                            selectedCodebase.updated_at
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 text-sm text-muted-foreground">
                    These are the chunks currently backing approved codebase memory. Recall and
                    reflect stay anchored to this snapshot until a newer review queue is explicitly
                    approved.
                  </div>

                  <div className="flex justify-end">
                    <Button
                      variant="outline"
                      disabled={
                        !selectedCodebaseId ||
                        !selectedCodebase.approved_snapshot_id ||
                        loadingApprovedChunks
                      }
                      onClick={() =>
                        selectedCodebaseId &&
                        selectedCodebase.approved_snapshot_id &&
                        void loadApprovedChunks(
                          selectedCodebaseId,
                          selectedCodebase.approved_snapshot_id
                        )
                      }
                    >
                      {loadingApprovedChunks ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <CheckCircle2 className="mr-2 h-4 w-4" />
                      )}
                      Refresh Approved History
                    </Button>
                  </div>

                  {approvedChunksResult?.items?.length ? (
                    <div className="grid gap-4 xl:grid-cols-2">
                      {approvedChunksResult.items.map((item) => (
                        <Card key={item.id} className="border-border/70 bg-background/50">
                          <CardContent className="space-y-4 p-5">
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div className="min-w-0 space-y-1">
                                <div className="break-words text-base font-semibold text-foreground [overflow-wrap:anywhere]">
                                  {item.label}
                                </div>
                                <div className="line-clamp-3 text-sm text-muted-foreground">
                                  {item.preview_text}
                                </div>
                              </div>
                              <span
                                className={`rounded-full px-2.5 py-1 text-xs font-semibold ${routeTone(item.route_target)}`}
                              >
                                {formatStatusLabel(item.route_target)}
                              </span>
                            </div>

                            <div className="grid gap-3 sm:grid-cols-2">
                              <div className="space-y-1">
                                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                  Path
                                </div>
                                <HoverPath
                                  value={`${item.path}:${item.start_line}-${item.end_line}`}
                                />
                              </div>
                              <div className="space-y-1">
                                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                  Document
                                </div>
                                <HoverPath value={item.document_id || "Not hydrated"} />
                              </div>
                              <div className="space-y-1">
                                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                  Symbol
                                </div>
                                <div className="break-words text-sm text-foreground [overflow-wrap:anywhere]">
                                  {item.parent_symbol || item.container || "-"}
                                </div>
                              </div>
                              <div className="space-y-1">
                                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                  Cluster
                                </div>
                                <div className="break-words text-sm text-foreground [overflow-wrap:anywhere]">
                                  {item.cluster_label || "-"}
                                </div>
                              </div>
                            </div>

                            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                              <span className="rounded-full bg-muted px-2.5 py-1">{item.kind}</span>
                              <span className="rounded-full bg-muted px-2.5 py-1">
                                {item.language || "unknown"}
                              </span>
                              <span className="rounded-full bg-muted px-2.5 py-1">
                                {item.related_count} related
                              </span>
                              <span className="rounded-full bg-muted px-2.5 py-1">
                                {(item.parse_confidence * 100).toFixed(0)}% parse confidence
                              </span>
                            </div>

                            <div className="flex justify-end">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => void openChunkDetail(item.id)}
                              >
                                Details
                              </Button>
                            </div>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  ) : loadingApprovedChunks ? (
                    <div className="flex items-center gap-3 rounded-lg border border-border/70 p-4 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Loading approved chunk history...
                    </div>
                  ) : (
                    <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                      No approved memory chunks are available yet for this codebase snapshot.
                    </div>
                  )}

                  {approvedChunksResult?.has_more && selectedCodebaseId ? (
                    <div className="flex justify-center">
                      <Button
                        variant="outline"
                        onClick={() =>
                          selectedCodebase.approved_snapshot_id &&
                          void loadApprovedChunks(
                            selectedCodebaseId,
                            selectedCodebase.approved_snapshot_id,
                            approvedChunksResult.next_cursor,
                            true
                          )
                        }
                        disabled={loadingApprovedChunks}
                      >
                        {loadingApprovedChunks ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <ChevronsRight className="mr-2 h-4 w-4" />
                        )}
                        Load More Approved Chunks
                      </Button>
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                  Approved chunk history appears here after the first successful memory approval for
                  this codebase.
                </div>
              )}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <Dialog
        open={memoryActionDialogOpen}
        onOpenChange={(open) => {
          setMemoryActionDialogOpen(open);
          if (!open) {
            setPendingMemoryAction(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              {pendingMemoryAction?.kind === "approve"
                ? "Choose Memory Ingest Path"
                : "Send Chunk To Memory"}
            </DialogTitle>
            <DialogDescription className="leading-relaxed">
              {pendingMemoryAction?.kind === "approve"
                ? "Choose how the routed ASD-reviewed chunks should enter memory. Direct mode is exact and fast. Retain mode is heavier, but it uses Atulya's richer ingest path with ASD context."
                : "Choose whether this ASD-reviewed chunk should enter memory directly or go through the richer retain pipeline with extra ASD context."}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 md:grid-cols-2">
            {(["retain", "direct"] as CodebaseMemoryIngestMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setMemoryIngestMode(mode)}
                className={`rounded-xl border p-4 text-left transition-colors ${
                  memoryIngestMode === mode
                    ? "border-primary bg-primary/5"
                    : "border-border/70 bg-background hover:bg-muted/20"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-foreground">
                    {memoryIngestModeLabel(mode)}
                    {mode === "retain" ? " (Recommended)" : ""}
                  </div>
                  <span
                    className={`inline-flex min-h-8 items-center whitespace-nowrap rounded-full px-3 py-1 text-[11px] font-semibold leading-none ${
                      mode === "retain"
                        ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                        : "bg-amber-500/10 text-amber-700 dark:text-amber-300"
                    }`}
                  >
                    {mode === "retain" ? "Richer linking" : "Fastest path"}
                  </span>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  {memoryIngestModeDescription(mode)}
                </p>
              </button>
            ))}
          </div>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-lg border border-border/70 p-3">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">Action</div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {pendingMemoryAction?.kind === "approve"
                  ? "Approve Routed Memory"
                  : "Route And Queue"}
              </div>
            </div>
            <div className="rounded-lg border border-border/70 p-3">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">Chunks</div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {pendingMemoryAction?.chunkCount || 0}
              </div>
            </div>
            <div className="rounded-lg border border-border/70 p-3">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">Symbol</div>
              <div className="mt-1 break-words text-sm font-medium text-foreground [overflow-wrap:anywhere]">
                {pendingMemoryAction?.previewChunk?.parent_symbol ||
                  pendingMemoryAction?.previewChunk?.container ||
                  "-"}
              </div>
            </div>
            <div className="rounded-lg border border-border/70 p-3">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">Cluster</div>
              <div className="mt-1 break-words text-sm font-medium text-foreground [overflow-wrap:anywhere]">
                {pendingMemoryAction?.previewChunk?.cluster_label || "-"}
              </div>
            </div>
          </div>

          {pendingMemoryAction?.previewChunk ? (
            <div className="rounded-xl border border-border/70 bg-muted/10 p-4">
              <div className="mb-2 text-sm font-semibold text-foreground">ASD Context Preview</div>
              <div className="space-y-2">
                <HoverPath
                  value={`${pendingMemoryAction.previewChunk.path}:${pendingMemoryAction.previewChunk.start_line}-${pendingMemoryAction.previewChunk.end_line}`}
                />
                <div className="line-clamp-4 text-sm text-muted-foreground">
                  {pendingMemoryAction.previewChunk.preview_text}
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <span className="rounded-full bg-muted px-2.5 py-1">
                    {pendingMemoryAction.previewChunk.kind}
                  </span>
                  <span className="rounded-full bg-muted px-2.5 py-1">
                    {pendingMemoryAction.previewChunk.language || "unknown"}
                  </span>
                  <span className="rounded-full bg-muted px-2.5 py-1">
                    {pendingMemoryAction.previewChunk.related_count} related
                  </span>
                  <span className="rounded-full bg-muted px-2.5 py-1">
                    {(pendingMemoryAction.previewChunk.parse_confidence * 100).toFixed(0)}% parse
                    confidence
                  </span>
                </div>
              </div>
            </div>
          ) : null}

          <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 text-sm text-muted-foreground">
            {memoryIngestMode === "retain"
              ? "Retain mode sends the reviewed code through Atulya's richer ingest path with ASD-generated context. This is heavier, but better for relationships, semantic retrieval, and future synthesis."
              : "ASD Direct mode stores the exact reviewed chunk as memory immediately. It is deterministic and efficient, but it intentionally skips the richer retain-time linking path."}
          </div>

          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              variant="outline"
              onClick={() => {
                setMemoryActionDialogOpen(false);
                setPendingMemoryAction(null);
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void confirmMemoryAction()}
              disabled={routingTarget !== null || approvingCodebase}
            >
              {pendingMemoryAction?.kind === "approve"
                ? `Queue ${memoryIngestModeLabel(memoryIngestMode)}`
                : `Send Via ${memoryIngestModeLabel(memoryIngestMode)}`}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={chunkDialogOpen} onOpenChange={setChunkDialogOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-5xl">
          <DialogHeader>
            <DialogTitle className="break-words pr-10 [overflow-wrap:anywhere]">
              {chunkDetail?.label || "Chunk Detail"}
            </DialogTitle>
            <DialogDescription className="break-words [overflow-wrap:anywhere]">
              Inspect the semantic chunk, its symbol context, related chunks, and route actions
              before deciding whether it belongs in memory or the research queue.
            </DialogDescription>
          </DialogHeader>

          {loadingChunkDetail ? (
            <div className="flex items-center gap-3 rounded-lg border border-border/70 p-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading chunk detail...
            </div>
          ) : chunkDetail ? (
            <div className="space-y-6">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <div className="min-w-0 rounded-lg border border-border/70 p-3">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Path</div>
                  <div className="mt-1 break-all font-mono text-xs leading-relaxed text-foreground">
                    {chunkDetail.path}:{chunkDetail.start_line}-{chunkDetail.end_line}
                  </div>
                </div>
                <div className="min-w-0 rounded-lg border border-border/70 p-3">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Route</div>
                  <div className="mt-1">
                    <span
                      className={`rounded-full px-2.5 py-1 text-xs font-semibold ${routeTone(chunkDetail.route_target)}`}
                    >
                      {formatStatusLabel(chunkDetail.route_target)}
                    </span>
                  </div>
                </div>
                <div className="min-w-0 rounded-lg border border-border/70 p-3">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">
                    Cluster
                  </div>
                  <div className="mt-1 break-words text-sm font-medium leading-relaxed text-foreground [overflow-wrap:anywhere]">
                    {chunkDetail.cluster_label || "-"}
                  </div>
                </div>
                <div className="min-w-0 rounded-lg border border-border/70 p-3">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">
                    Parse Confidence
                  </div>
                  <div className="mt-1 text-sm font-medium text-foreground">
                    {(chunkDetail.parse_confidence * 100).toFixed(0)}%
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  onClick={() =>
                    openMemoryActionDialog({
                      kind: "route",
                      itemIds: [chunkDetail.id],
                      chunkCount: 1,
                      previewChunk: chunkDetail,
                    })
                  }
                >
                  Send To Memory
                </Button>
                <Button
                  variant="outline"
                  onClick={() => void handleRouteItems("research", [chunkDetail.id])}
                >
                  Send To Research
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => void handleRouteItems("dismissed", [chunkDetail.id])}
                >
                  Dismiss
                </Button>
              </div>

              <div className="min-w-0 rounded-xl border border-border/70 bg-muted/20 p-4">
                <div className="mb-2 text-sm font-semibold text-foreground">Code Preview</div>
                <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground [overflow-wrap:anywhere]">
                  {chunkDetail.content_text}
                </pre>
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <div className="rounded-xl border border-border/70 p-4">
                  <div className="mb-3 text-sm font-semibold text-foreground">
                    Top Related Chunks
                  </div>
                  <div className="space-y-2">
                    {chunkDetail.related_chunks.length ? (
                      chunkDetail.related_chunks.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          className="w-full rounded-lg border border-border/60 bg-background/70 p-3 text-left hover:bg-muted/20"
                          onClick={() => void openChunkDetail(item.id)}
                        >
                          <div className="break-words font-medium text-foreground [overflow-wrap:anywhere]">
                            {item.label}
                          </div>
                          <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
                            {item.path}:{item.start_line}-{item.end_line}
                          </div>
                          <div className="mt-2 text-xs text-muted-foreground">
                            Similarity {(item.score * 100).toFixed(0)}%
                          </div>
                        </button>
                      ))
                    ) : (
                      <div className="text-sm text-muted-foreground">
                        No related chunks were precomputed.
                      </div>
                    )}
                  </div>
                </div>

                <div className="rounded-xl border border-border/70 p-4">
                  <div className="mb-3 text-sm font-semibold text-foreground">Symbol Context</div>
                  <div className="space-y-2">
                    {chunkDetail.symbols.length ? (
                      chunkDetail.symbols.map((item) => (
                        <div
                          key={`${item.fq_name}-${item.start_line}`}
                          className="rounded-lg border border-border/60 p-3"
                        >
                          <div className="break-words font-medium text-foreground [overflow-wrap:anywhere]">
                            {item.name}
                          </div>
                          <div className="mt-1 break-all text-xs leading-relaxed text-muted-foreground">
                            {item.kind} · {item.path}:{item.start_line}-{item.end_line}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="text-sm text-muted-foreground">
                        No symbols overlap this chunk.
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <div className="rounded-xl border border-border/70 p-4">
                  <div className="mb-3 text-sm font-semibold text-foreground">Impact Edges</div>
                  <div className="space-y-2">
                    {chunkDetail.impact_edges.length ? (
                      chunkDetail.impact_edges.map((edge, index) => (
                        <div
                          key={`${edge.from_path}-${edge.to_path}-${index}`}
                          className="rounded-lg border border-border/60 p-3"
                        >
                          <div className="break-all font-mono text-xs text-foreground">
                            {edge.from_path}
                          </div>
                          <div className="my-1 text-xs uppercase tracking-wide text-muted-foreground">
                            {edge.edge_type}
                          </div>
                          <div className="break-all font-mono text-xs text-foreground">
                            {edge.to_path || edge.target_ref || "external target"}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="text-sm text-muted-foreground">
                        No impact edges touch this chunk path.
                      </div>
                    )}
                  </div>
                </div>

                <div className="rounded-xl border border-border/70 p-4">
                  <div className="mb-3 text-sm font-semibold text-foreground">Cluster Members</div>
                  <div className="space-y-2">
                    {chunkDetail.cluster_members.length ? (
                      chunkDetail.cluster_members.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          className="w-full rounded-lg border border-border/60 bg-background/70 p-3 text-left hover:bg-muted/20"
                          onClick={() => void openChunkDetail(item.id)}
                        >
                          <div className="break-words font-medium text-foreground [overflow-wrap:anywhere]">
                            {item.label}
                          </div>
                          <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
                            {item.path}:{item.start_line}-{item.end_line}
                          </div>
                        </button>
                      ))
                    ) : (
                      <div className="text-sm text-muted-foreground">
                        This chunk does not have additional cluster members.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
              Pick a chunk from the review queue to inspect its detail surface.
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={triageSettingsOpen} onOpenChange={setTriageSettingsOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Tune auto-triage settings</DialogTitle>
            <DialogDescription>
              Thresholds run in [0..1]. Lower values pull more chunks into{" "}
              <span className="font-medium">memory</span>; raise them to keep the gold layer
              tighter. Changes apply on the next index pass.
            </DialogDescription>
          </DialogHeader>

          {triageDraft ? (
            <div className="space-y-4 text-sm">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="triage-high">High score threshold</Label>
                  <Input
                    id="triage-high"
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={triageDraft.score_threshold_high}
                    onChange={(event) =>
                      setTriageDraft((current) =>
                        current
                          ? {
                              ...current,
                              score_threshold_high: Math.max(
                                0,
                                Math.min(1, Number(event.target.value) || 0)
                              ),
                            }
                          : current
                      )
                    }
                  />
                  <p className="text-[11px] text-muted-foreground">
                    Default 0.62. Chunks above this with high centrality auto-route to memory.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="triage-centrality">Centrality threshold</Label>
                  <Input
                    id="triage-centrality"
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={triageDraft.centrality_threshold}
                    onChange={(event) =>
                      setTriageDraft((current) =>
                        current
                          ? {
                              ...current,
                              centrality_threshold: Math.max(
                                0,
                                Math.min(1, Number(event.target.value) || 0)
                              ),
                            }
                          : current
                      )
                    }
                  />
                  <p className="text-[11px] text-muted-foreground">
                    Default 0.35. PageRank cutoff for the &ldquo;exported + central&rdquo; rule.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="triage-safety">Safety centrality threshold</Label>
                  <Input
                    id="triage-safety"
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={triageDraft.safety_threshold}
                    onChange={(event) =>
                      setTriageDraft((current) =>
                        current
                          ? {
                              ...current,
                              safety_threshold: Math.max(
                                0,
                                Math.min(1, Number(event.target.value) || 0)
                              ),
                            }
                          : current
                      )
                    }
                  />
                  <p className="text-[11px] text-muted-foreground">
                    Default 0.25. Min PageRank to auto-promote safety-critical chunks to memory.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="triage-embed">Embedding provider</Label>
                  <Select
                    value={triageDraft.embedding_provider}
                    onValueChange={(value) =>
                      setTriageDraft((current) =>
                        current ? { ...current, embedding_provider: value } : current
                      )
                    }
                  >
                    <SelectTrigger id="triage-embed">
                      <SelectValue placeholder="Provider" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="jina_local">Jina v2 code (local)</SelectItem>
                      <SelectItem value="voyage_code_3">Voyage code-3 (paid)</SelectItem>
                      <SelectItem value="generic">Generic engine fallback</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid gap-4 rounded-xl border border-border/70 bg-muted/10 p-3 sm:grid-cols-2">
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Checkbox
                    checked={triageDraft.enable_safety_scan}
                    onCheckedChange={(value) =>
                      setTriageDraft((current) =>
                        current ? { ...current, enable_safety_scan: value === true } : current
                      )
                    }
                  />
                  <span>Built-in safety scan (auth/crypto/sql/eval/...)</span>
                </label>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Checkbox
                    checked={triageDraft.enable_semgrep}
                    onCheckedChange={(value) =>
                      setTriageDraft((current) =>
                        current ? { ...current, enable_semgrep: value === true } : current
                      )
                    }
                  />
                  <span>Run Semgrep curated rulepack (requires CLI installed)</span>
                </label>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="triage-rulepack">Semgrep rulepack</Label>
                  <Input
                    id="triage-rulepack"
                    placeholder="p/owasp-top-ten or path to rules"
                    value={triageDraft.semgrep_rulepack ?? ""}
                    onChange={(event) =>
                      setTriageDraft((current) =>
                        current
                          ? {
                              ...current,
                              semgrep_rulepack: event.target.value.trim() || null,
                            }
                          : current
                      )
                    }
                  />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="triage-scip">SCIP index path (optional)</Label>
                  <Input
                    id="triage-scip"
                    placeholder="path/to/index.scip"
                    value={triageDraft.scip_index_path ?? ""}
                    onChange={(event) =>
                      setTriageDraft((current) =>
                        current
                          ? {
                              ...current,
                              scip_index_path: event.target.value.trim() || null,
                            }
                          : current
                      )
                    }
                  />
                  <p className="text-[11px] text-muted-foreground">
                    When present, precise cross-references replace the tree-sitter heuristics.
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setTriageSettingsOpen(false)}
                  disabled={savingTriageSettings}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => void saveTriageSettings()}
                  disabled={savingTriageSettings}
                >
                  {savingTriageSettings ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Save settings
                </Button>
              </div>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">Loading current settings...</div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
