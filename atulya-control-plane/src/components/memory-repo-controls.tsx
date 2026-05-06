"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { client, type MemoryRepoBranchSummary, type MemoryRepoCommitLogItem } from "@/lib/api";
import { useBank } from "@/lib/bank-context";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  AlertTriangle,
  CheckCircle2,
  GitBranch,
  GitCommitHorizontal,
  Loader2,
  Plus,
  RefreshCw,
  RotateCcw,
} from "lucide-react";

type MemoryRepoControlsProps = {
  variant?: "compact" | "full";
};

function formatRepoTime(value: string | null): string {
  if (!value) return "Never";
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function shortCommit(commitId: string | null): string {
  return commitId ? commitId.slice(0, 8) : "No commits";
}

function statusTone(dirty: boolean | undefined) {
  return dirty
    ? "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/20"
    : "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20";
}

function tableDeltaEntries(
  tableDeltas: Record<string, { before: number; after: number; delta: number }>
) {
  return Object.entries(tableDeltas).sort((left, right) => left[0].localeCompare(right[0]));
}

export function MemoryRepoControls({ variant = "full" }: MemoryRepoControlsProps) {
  const {
    currentBank,
    currentRepo,
    repoBranches,
    repoStatus,
    repoLoading,
    refreshRepo,
    bumpBankRevision,
  } = useBank();

  const [enableDialogOpen, setEnableDialogOpen] = useState(false);
  const [repoName, setRepoName] = useState("");
  const [enablingRepo, setEnablingRepo] = useState(false);

  const [branchDialogOpen, setBranchDialogOpen] = useState(false);
  const [branchName, setBranchName] = useState("");
  const [branchFromCommitId, setBranchFromCommitId] = useState("__head__");
  const [creatingBranch, setCreatingBranch] = useState(false);

  const [commitDialogOpen, setCommitDialogOpen] = useState(false);
  const [commitMessage, setCommitMessage] = useState("");
  const [committing, setCommitting] = useState(false);

  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [resetCommitId, setResetCommitId] = useState("");
  const [resetForce, setResetForce] = useState(false);
  const [resetting, setResetting] = useState(false);

  const [checkingOutBranch, setCheckingOutBranch] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [logItems, setLogItems] = useState<MemoryRepoCommitLogItem[]>([]);
  const [logLoading, setLogLoading] = useState(false);

  const changedComponents = repoStatus?.changed_components || [];
  const changedTables = useMemo(
    () => tableDeltaEntries(repoStatus?.table_deltas || {}),
    [repoStatus?.table_deltas]
  );
  const branchSummaries = repoBranches.length > 0 ? repoBranches : currentRepo?.branches || [];
  const activeBranch = currentRepo?.active_branch || "";
  const activeBranchSummary =
    branchSummaries.find((item) => item.branch_name === activeBranch) || null;
  const displayedHeadCommitId =
    activeBranchSummary?.head_commit_id || currentRepo?.head_commit_id || null;
  const displayedHeadMessage =
    activeBranchSummary?.head_message || currentRepo?.head_message || null;
  const displayedHeadCreatedAt =
    activeBranchSummary?.head_created_at || currentRepo?.head_created_at || null;
  const isCompact = variant === "compact";
  const hasRepo = Boolean(currentRepo);

  useEffect(() => {
    setResetCommitId("");
    setResetForce(false);
  }, [currentRepo?.active_branch, currentRepo?.repo_id]);

  useEffect(() => {
    let cancelled = false;

    async function loadLog() {
      if (!currentRepo || variant !== "full") {
        setLogItems([]);
        return;
      }

      setLogLoading(true);
      try {
        const response = await client.getMemoryRepoLog(currentRepo.repo_id, {
          branchName: currentRepo.active_branch,
          limit: 12,
        });
        if (!cancelled) {
          setLogItems(response.commits || []);
          if (!resetCommitId && response.commits?.[0]?.commit_id) {
            setResetCommitId(response.commits[0].commit_id);
          }
        }
      } catch (error) {
        if (!cancelled) {
          console.error("Error loading memory repo log:", error);
        }
      } finally {
        if (!cancelled) {
          setLogLoading(false);
        }
      }
    }

    void loadLog();
    return () => {
      cancelled = true;
    };
  }, [currentRepo?.active_branch, currentRepo?.repo_id, refreshNonce, variant]);

  useEffect(() => {
    if (!commitDialogOpen && repoStatus?.dirty) {
      setCommitMessage((current) => current || `Update ${activeBranch} workspace`);
    }
  }, [activeBranch, commitDialogOpen, repoStatus?.dirty]);

  const triggerRefresh = async (options?: { refreshBankView?: boolean }) => {
    await refreshRepo();
    setRefreshNonce((value) => value + 1);
    if (options?.refreshBankView) {
      bumpBankRevision();
    }
  };

  const handleEnableRepo = async () => {
    if (!currentBank) return;
    setEnablingRepo(true);
    try {
      await client.enableMemoryRepo(currentBank, repoName.trim() || undefined);
      await triggerRefresh();
      setEnableDialogOpen(false);
      setRepoName("");
      toast.success("Versioning enabled", {
        description: "This bank now has git-like memory branches and commits.",
      });
    } finally {
      setEnablingRepo(false);
    }
  };

  const handleCheckout = async (branchNameValue: string) => {
    if (!currentRepo || branchNameValue === currentRepo.active_branch) return;
    setCheckingOutBranch(branchNameValue);
    try {
      await client.checkoutMemoryRepo(currentRepo.repo_id, branchNameValue);
      await triggerRefresh({ refreshBankView: true });
      toast.success("Branch switched", {
        description: `Workspace is now on ${branchNameValue}.`,
      });
    } finally {
      setCheckingOutBranch(null);
    }
  };

  const handleCreateBranch = async () => {
    if (!currentRepo || !branchName.trim()) return;
    setCreatingBranch(true);
    try {
      await client.createMemoryRepoBranch(currentRepo.repo_id, {
        branchName: branchName.trim(),
        fromCommitId: branchFromCommitId !== "__head__" ? branchFromCommitId : undefined,
      });
      await triggerRefresh();
      setBranchDialogOpen(false);
      setBranchName("");
      setBranchFromCommitId("__head__");
      toast.success("Branch created", {
        description: `Created ${branchName.trim()} from ${
          branchFromCommitId === "__head__" ? "current HEAD" : shortCommit(branchFromCommitId)
        }.`,
      });
    } finally {
      setCreatingBranch(false);
    }
  };

  const handleCommit = async () => {
    if (!currentRepo || !commitMessage.trim()) return;
    setCommitting(true);
    try {
      await client.commitMemoryRepo(currentRepo.repo_id, {
        message: commitMessage.trim(),
        actor: "control-plane",
      });
      await triggerRefresh();
      setCommitDialogOpen(false);
      setCommitMessage("");
      toast.success("Workspace committed", {
        description: "The active branch HEAD now points to your latest snapshot.",
      });
    } finally {
      setCommitting(false);
    }
  };

  const handleReset = async () => {
    if (!currentRepo || !resetCommitId) return;
    setResetting(true);
    try {
      await client.resetMemoryRepoHard(currentRepo.repo_id, {
        commitId: resetCommitId,
        force: resetForce,
      });
      await triggerRefresh({ refreshBankView: true });
      setResetDialogOpen(false);
      toast.success("Branch reset", {
        description: `Workspace restored to ${shortCommit(resetCommitId)}.`,
      });
    } finally {
      setResetting(false);
    }
  };

  if (!currentBank) {
    return null;
  }

  if (isCompact) {
    return (
      <>
        <div className="flex min-w-0 items-center gap-2">
          {!hasRepo ? (
            <Button
              variant="outline"
              size="sm"
              className="h-9 gap-1.5 border-dashed"
              onClick={() => setEnableDialogOpen(true)}
              disabled={repoLoading || enablingRepo}
            >
              {repoLoading || enablingRepo ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <GitBranch className="h-4 w-4" />
              )}
              <span className="hidden xl:inline">Enable Versioning</span>
              <span className="xl:hidden">Versioning</span>
            </Button>
          ) : (
            <div className="flex min-w-0 items-center gap-2 rounded-lg border border-border bg-background/70 px-2 py-1">
              <Select value={activeBranch} onValueChange={(value) => void handleCheckout(value)}>
                <SelectTrigger className="h-8 w-[148px] border-0 bg-transparent px-2 shadow-none">
                  <SelectValue placeholder="Branch" />
                </SelectTrigger>
                <SelectContent>
                  {branchSummaries.map((branch) => (
                    <SelectItem key={branch.branch_name} value={branch.branch_name}>
                      {branch.branch_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span
                className={cn(
                  "rounded-full border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide",
                  statusTone(repoStatus?.dirty)
                )}
              >
                {repoStatus?.dirty ? "Dirty" : "Clean"}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 px-2"
                onClick={() => setBranchDialogOpen(true)}
                title="Create branch"
              >
                <Plus className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 px-2"
                onClick={() => setCommitDialogOpen(true)}
                disabled={!repoStatus?.dirty}
                title="Commit workspace"
              >
                <GitCommitHorizontal className="h-4 w-4" />
              </Button>
              {checkingOutBranch ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              ) : null}
            </div>
          )}
        </div>
        <MemoryRepoDialogs
          branchDialogOpen={branchDialogOpen}
          branchFromCommitId={branchFromCommitId}
          branchName={branchName}
          commitDialogOpen={commitDialogOpen}
          commitMessage={commitMessage}
          creatingBranch={creatingBranch}
          currentRepoBranches={branchSummaries}
          enableDialogOpen={enableDialogOpen}
          enablingRepo={enablingRepo}
          hasRepo={hasRepo}
          logItems={logItems}
          onBranchDialogOpenChange={setBranchDialogOpen}
          onBranchFromCommitIdChange={setBranchFromCommitId}
          onBranchNameChange={setBranchName}
          onCommitDialogOpenChange={setCommitDialogOpen}
          onCommitMessageChange={setCommitMessage}
          onCreateBranch={handleCreateBranch}
          onEnableDialogOpenChange={setEnableDialogOpen}
          onEnableRepo={handleEnableRepo}
          onRepoNameChange={setRepoName}
          onCommit={handleCommit}
          repoName={repoName}
          committing={committing}
        />
      </>
    );
  }

  return (
    <>
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-3 text-xl">
            <GitBranch className="h-5 w-5 text-primary" />
            Memory Repo
          </CardTitle>
          <CardDescription>
            Create safe bank versions, review changes, and roll back with confidence.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {!hasRepo ? (
            <div className="rounded-xl border border-dashed border-border bg-muted/20 p-5">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="space-y-2">
                  <h3 className="text-base font-semibold text-foreground">
                    Turn this bank into a versioned memory repo
                  </h3>
                  <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                    Versioning keeps this bank as the live workspace for the selected branch while
                    other branches stay isolated behind the scenes. That gives you safe `main`,
                    `v1`, and `experiment/*` flows without polluting live memory.
                  </p>
                </div>
                <Button
                  onClick={() => setEnableDialogOpen(true)}
                  disabled={repoLoading || enablingRepo}
                >
                  {repoLoading || enablingRepo ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <GitBranch className="mr-2 h-4 w-4" />
                  )}
                  Enable Versioning
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <RepoStatCard
                  label="Active branch"
                  value={activeBranch}
                  hint={currentRepo?.name || currentBank}
                />
                <RepoStatCard
                  label="Current snapshot"
                  value={shortCommit(displayedHeadCommitId)}
                  hint={displayedHeadMessage || "No saved snapshot yet"}
                />
                <RepoStatCard
                  label="Workspace state"
                  value={repoStatus?.dirty ? "Dirty" : "Clean"}
                  hint={
                    repoStatus?.dirty
                      ? `${changedComponents.length} components changed`
                      : "No changes since the latest snapshot"
                  }
                  tone={repoStatus?.dirty ? "warn" : "ok"}
                />
                <RepoStatCard
                  label="Last saved"
                  value={formatRepoTime(displayedHeadCreatedAt)}
                  hint={displayedHeadMessage || "No snapshot saved yet"}
                />
              </div>

              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-background/60 p-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  <Select
                    value={activeBranch}
                    onValueChange={(value) => void handleCheckout(value)}
                  >
                    <SelectTrigger className="w-full sm:w-[220px]">
                      <SelectValue placeholder="Select branch" />
                    </SelectTrigger>
                    <SelectContent>
                      {branchSummaries.map((branch) => (
                        <SelectItem key={branch.branch_name} value={branch.branch_name}>
                          {branch.branch_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button variant="outline" onClick={() => setBranchDialogOpen(true)}>
                    <Plus className="mr-2 h-4 w-4" />
                    Create Branch
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => setCommitDialogOpen(true)}
                    disabled={!repoStatus?.dirty}
                  >
                    <GitCommitHorizontal className="mr-2 h-4 w-4" />
                    Commit
                  </Button>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="outline" onClick={() => void triggerRefresh()}>
                    <RefreshCw className="mr-2 h-4 w-4" />
                    Refresh
                  </Button>
                  <Button
                    variant="outline"
                    className="text-amber-700 dark:text-amber-300"
                    onClick={() => setResetDialogOpen(true)}
                  >
                    <RotateCcw className="mr-2 h-4 w-4" />
                    Restore Snapshot
                  </Button>
                  {checkingOutBranch ? (
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                  ) : null}
                </div>
              </div>

              {repoStatus?.dirty ? (
                <Alert className="border-amber-500/20 bg-amber-500/5 text-amber-800 dark:text-amber-200">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Uncommitted workspace changes</AlertTitle>
                  <AlertDescription>
                    Branch checkout is isolated, but this branch still has changes that are not part
                    of the latest snapshot. Commit them before promotion or restore an older
                    snapshot to discard them.
                  </AlertDescription>
                </Alert>
              ) : (
                <Alert className="border-emerald-500/20 bg-emerald-500/5 text-emerald-800 dark:text-emerald-200">
                  <CheckCircle2 className="h-4 w-4" />
                  <AlertTitle>Workspace is clean</AlertTitle>
                  <AlertDescription>
                    {activeBranch} is currently in sync with its HEAD commit.
                  </AlertDescription>
                </Alert>
              )}

              <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
                <div className="space-y-4 rounded-xl border border-border/70 bg-background/50 p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-base font-semibold text-foreground">Workspace changes</h3>
                      <p className="text-sm text-muted-foreground">
                        Live workspace versus the latest snapshot for {activeBranch}.
                      </p>
                    </div>
                    <span
                      className={cn(
                        "rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide",
                        statusTone(repoStatus?.dirty)
                      )}
                    >
                      {repoStatus?.dirty ? "Dirty" : "Clean"}
                    </span>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {changedComponents.length > 0 ? (
                      changedComponents.map((component) => (
                        <span
                          key={component}
                          className="rounded-full border border-border bg-muted/60 px-2.5 py-1 text-xs font-medium text-foreground"
                        >
                          {component}
                        </span>
                      ))
                    ) : (
                      <span className="text-sm text-muted-foreground">No changed components.</span>
                    )}
                  </div>

                  <div className="space-y-2">
                    {changedTables.length > 0 ? (
                      changedTables.map(([table, delta]) => (
                        <div
                          key={table}
                          className="flex items-center justify-between rounded-lg border border-border/60 bg-muted/25 px-3 py-2 text-sm"
                        >
                          <span className="font-medium text-foreground">{table}</span>
                          <span className="text-muted-foreground">
                            {delta.before} → {delta.after}
                            <span
                              className={cn(
                                "ml-2 font-semibold",
                                delta.delta >= 0
                                  ? "text-emerald-600 dark:text-emerald-300"
                                  : "text-red-600 dark:text-red-300"
                              )}
                            >
                              {delta.delta >= 0 ? "+" : ""}
                              {delta.delta}
                            </span>
                          </span>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-4 text-sm text-muted-foreground">
                        No workspace changes compared with the latest snapshot.
                      </div>
                    )}
                  </div>
                </div>

                <div className="space-y-4 rounded-xl border border-border/70 bg-background/50 p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-base font-semibold text-foreground">Recent commits</h3>
                      <p className="text-sm text-muted-foreground">
                        Current branch history for fast rollback and review.
                      </p>
                    </div>
                    {logLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                    ) : null}
                  </div>

                  <div className="space-y-3">
                    {logItems.length > 0 ? (
                      logItems.map((commit) => (
                        <div
                          key={commit.commit_id}
                          className="rounded-lg border border-border/60 bg-muted/20 px-3 py-3"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="truncate text-sm font-semibold text-foreground">
                                {commit.message}
                              </p>
                              <p className="mt-1 text-xs text-muted-foreground">
                                {shortCommit(commit.commit_id)} ·{" "}
                                {formatRepoTime(commit.created_at)}
                                {commit.actor ? ` · ${commit.actor}` : ""}
                              </p>
                            </div>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 px-2 text-amber-700 dark:text-amber-300"
                              onClick={() => {
                                setResetCommitId(commit.commit_id);
                                setResetDialogOpen(true);
                              }}
                            >
                              <RotateCcw className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-4 text-sm text-muted-foreground">
                        No commits available yet.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <MemoryRepoDialogs
        branchDialogOpen={branchDialogOpen}
        branchFromCommitId={branchFromCommitId}
        branchName={branchName}
        commitDialogOpen={commitDialogOpen}
        commitMessage={commitMessage}
        creatingBranch={creatingBranch}
        currentRepoBranches={branchSummaries}
        enableDialogOpen={enableDialogOpen}
        enablingRepo={enablingRepo}
        hasRepo={hasRepo}
        logItems={logItems}
        onBranchDialogOpenChange={setBranchDialogOpen}
        onBranchFromCommitIdChange={setBranchFromCommitId}
        onBranchNameChange={setBranchName}
        onCommitDialogOpenChange={setCommitDialogOpen}
        onCommitMessageChange={setCommitMessage}
        onCreateBranch={handleCreateBranch}
        onEnableDialogOpenChange={setEnableDialogOpen}
        onEnableRepo={handleEnableRepo}
        onRepoNameChange={setRepoName}
        onCommit={handleCommit}
        repoName={repoName}
        committing={committing}
      />

      <Dialog open={resetDialogOpen} onOpenChange={setResetDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Restore branch to a snapshot</DialogTitle>
            <DialogDescription>
              This rewrites the active workspace for {activeBranch} to an earlier saved snapshot.
              Use force only when you want to discard uncommitted edits.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Target commit</label>
              <Select value={resetCommitId} onValueChange={setResetCommitId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select commit" />
                </SelectTrigger>
                <SelectContent>
                  {logItems.map((commit) => (
                    <SelectItem key={commit.commit_id} value={commit.commit_id}>
                      {shortCommit(commit.commit_id)} · {commit.message}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <label className="flex items-start gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-3">
              <Checkbox
                checked={resetForce}
                onCheckedChange={(checked) => setResetForce(Boolean(checked))}
              />
              <span className="space-y-1">
                <span className="block text-sm font-medium text-foreground">
                  Discard uncommitted changes if needed
                </span>
                <span className="block text-xs leading-5 text-muted-foreground">
                  If the workspace is dirty, allow restore to replace those edits with the selected
                  snapshot.
                </span>
              </span>
            </label>
          </div>
          <DialogFooter>
            <Button
              variant="secondary"
              onClick={() => setResetDialogOpen(false)}
              disabled={resetting}
            >
              Cancel
            </Button>
            <Button onClick={handleReset} disabled={resetting || !resetCommitId}>
              {resetting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RotateCcw className="mr-2 h-4 w-4" />
              )}
              Restore Snapshot
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function RepoStatCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  hint: string;
  tone?: "default" | "ok" | "warn";
}) {
  return (
    <div
      className={cn(
        "rounded-xl border px-4 py-3",
        tone === "ok"
          ? "border-emerald-500/20 bg-emerald-500/5"
          : tone === "warn"
            ? "border-amber-500/20 bg-amber-500/5"
            : "border-border/70 bg-background/60"
      )}
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-2 truncate text-lg font-semibold text-foreground">{value}</p>
      <p className="mt-1 truncate text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

function MemoryRepoDialogs({
  branchDialogOpen,
  branchFromCommitId,
  branchName,
  commitDialogOpen,
  commitMessage,
  creatingBranch,
  currentRepoBranches,
  enableDialogOpen,
  enablingRepo,
  hasRepo,
  logItems,
  onBranchDialogOpenChange,
  onBranchFromCommitIdChange,
  onBranchNameChange,
  onCommitDialogOpenChange,
  onCommitMessageChange,
  onCreateBranch,
  onEnableDialogOpenChange,
  onEnableRepo,
  onRepoNameChange,
  onCommit,
  repoName,
  committing,
}: {
  branchDialogOpen: boolean;
  branchFromCommitId: string;
  branchName: string;
  commitDialogOpen: boolean;
  commitMessage: string;
  creatingBranch: boolean;
  currentRepoBranches: MemoryRepoBranchSummary[];
  enableDialogOpen: boolean;
  enablingRepo: boolean;
  hasRepo: boolean;
  logItems: MemoryRepoCommitLogItem[];
  onBranchDialogOpenChange: (open: boolean) => void;
  onBranchFromCommitIdChange: (value: string) => void;
  onBranchNameChange: (value: string) => void;
  onCommitDialogOpenChange: (open: boolean) => void;
  onCommitMessageChange: (value: string) => void;
  onCreateBranch: () => Promise<void>;
  onEnableDialogOpenChange: (open: boolean) => void;
  onEnableRepo: () => Promise<void>;
  onRepoNameChange: (value: string) => void;
  onCommit: () => Promise<void>;
  repoName: string;
  committing: boolean;
}) {
  return (
    <>
      <Dialog open={enableDialogOpen} onOpenChange={onEnableDialogOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Enable versioned memory repo</DialogTitle>
            <DialogDescription>
              This keeps the current bank as the live workspace and adds isolated branch versions
              behind the scenes.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Repo name</label>
            <Input
              value={repoName}
              onChange={(event) => onRepoNameChange(event.target.value)}
              placeholder="Optional display name"
            />
          </div>
          <DialogFooter>
            <Button
              variant="secondary"
              onClick={() => onEnableDialogOpenChange(false)}
              disabled={enablingRepo}
            >
              Cancel
            </Button>
            <Button onClick={() => void onEnableRepo()} disabled={enablingRepo}>
              {enablingRepo ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <GitBranch className="mr-2 h-4 w-4" />
              )}
              Enable Versioning
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={branchDialogOpen} onOpenChange={onBranchDialogOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create branch</DialogTitle>
            <DialogDescription>
              Start from the latest snapshot or pin this new branch to a specific saved snapshot.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Branch name</label>
              <Input
                value={branchName}
                onChange={(event) => onBranchNameChange(event.target.value)}
                placeholder="v1, v2, experiment/refactor"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Start from</label>
              <Select value={branchFromCommitId} onValueChange={onBranchFromCommitIdChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Current HEAD" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__head__">Latest snapshot</SelectItem>
                  {logItems.map((commit) => (
                    <SelectItem key={commit.commit_id} value={commit.commit_id}>
                      {shortCommit(commit.commit_id)} · {commit.message}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {hasRepo && currentRepoBranches.length > 0 ? (
              <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-3 text-xs text-muted-foreground">
                Existing branches:{" "}
                {currentRepoBranches.map((branch) => branch.branch_name).join(", ")}
              </div>
            ) : null}
          </div>
          <DialogFooter>
            <Button
              variant="secondary"
              onClick={() => onBranchDialogOpenChange(false)}
              disabled={creatingBranch}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void onCreateBranch()}
              disabled={creatingBranch || !branchName.trim()}
            >
              {creatingBranch ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Plus className="mr-2 h-4 w-4" />
              )}
              Create Branch
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={commitDialogOpen} onOpenChange={onCommitDialogOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Commit workspace</DialogTitle>
            <DialogDescription>
              Save the active branch workspace as an immutable snapshot.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Commit message</label>
            <Textarea
              value={commitMessage}
              onChange={(event) => onCommitMessageChange(event.target.value)}
              placeholder="Describe the memory or configuration change"
              className="min-h-[110px]"
            />
          </div>
          <DialogFooter>
            <Button
              variant="secondary"
              onClick={() => onCommitDialogOpenChange(false)}
              disabled={committing}
            >
              Cancel
            </Button>
            <Button onClick={() => void onCommit()} disabled={committing || !commitMessage.trim()}>
              {committing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <GitCommitHorizontal className="mr-2 h-4 w-4" />
              )}
              Commit
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
