"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Download, Link2, Loader2, Upload } from "lucide-react";
import { useBank } from "@/lib/bank-context";
import { useFeatures } from "@/lib/features-context";
import { client } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

type LearningType = "auto" | "distilled" | "structured" | "raw_mirror";

export function BrainView() {
  const { currentBank } = useBank();
  const { features } = useFeatures();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState<any | null>(null);
  const [predictions, setPredictions] = useState<any | null>(null);
  const [histogram, setHistogram] = useState<any | null>(null);
  const [importValidation, setImportValidation] = useState<string>("");
  const [influence, setInfluence] = useState<{
    summary: Record<string, unknown>;
    leaderboard: Array<{
      id: string;
      type: string;
      influence_score: number;
      access_count: number;
      text: string;
    }>;
    heatmap: Array<{ weekday: number; hour_utc: number; score: number }>;
    trend: Array<{ index: number; ewma: number }>;
  } | null>(null);
  const [influenceError, setInfluenceError] = useState<string>("");
  const [influenceEntityType, setInfluenceEntityType] = useState<
    "all" | "memory" | "chunk" | "mental_model"
  >("all");
  const [influenceTopK, setInfluenceTopK] = useState(8);

  const [remoteEndpoint, setRemoteEndpoint] = useState("");
  const [remoteBankId, setRemoteBankId] = useState("");
  const [remoteApiKey, setRemoteApiKey] = useState("");
  const [learningType, setLearningType] = useState<LearningType>("auto");
  const [learnStatus, setLearnStatus] = useState<string>("");
  const [isLearning, setIsLearning] = useState(false);
  const [remoteBanks, setRemoteBanks] = useState<Array<{ bank_id: string }>>([]);
  const [isFetchingBanks, setIsFetchingBanks] = useState(false);
  const [isProbingRemote, setIsProbingRemote] = useState(false);
  const [remoteCapabilities, setRemoteCapabilities] = useState<{
    capabilities: {
      version_ok: boolean;
      banks_ok: boolean;
      brain_export_ok: boolean;
      mental_models_ok: boolean;
      memories_ok: boolean;
      entities_ok: boolean;
      status_codes: Record<string, number | null>;
    };
    recommended_learning_type: LearningType;
  } | null>(null);

  const importExportEnabled = features?.brain_import_export ?? false;

  useEffect(() => {
    if (currentBank) {
      void refresh();
    }
  }, [currentBank]);

  const refresh = async () => {
    if (!currentBank) return;
    setIsLoading(true);
    try {
      const [statusData, predictionData, histogramData, influenceData] = await Promise.all([
        client.getBrainStatus(currentBank),
        client.getSubRoutinePredictions(currentBank, 24),
        client.getSubRoutineHistogram(currentBank),
        client.getBrainInfluence(currentBank, {
          window_days: 14,
          top_k: influenceTopK,
          entity_type: influenceEntityType,
        }),
      ]);
      setStatus(statusData);
      setPredictions(predictionData);
      setHistogram(histogramData);
      setInfluence(influenceData);
      setInfluenceError("");
    } catch (error) {
      console.error("Failed to refresh brain view:", error);
      setInfluenceError(
        error instanceof Error ? error.message : "Failed to fetch influence snapshot"
      );
    } finally {
      setIsLoading(false);
    }
  };

  const influenceTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const item of influence?.leaderboard ?? []) {
      counts[item.type] = (counts[item.type] || 0) + 1;
    }
    return counts;
  }, [influence]);

  const miniHeatmapRows =
    influence?.heatmap.reduce<Array<Array<{ weekday: number; hour_utc: number; score: number }>>>(
      (acc, cell) => {
        if (!acc[cell.weekday]) acc[cell.weekday] = [];
        acc[cell.weekday].push(cell);
        return acc;
      },
      []
    ) ?? [];

  const runSubRoutine = async () => {
    if (!currentBank) return;
    setIsLoading(true);
    try {
      await client.triggerSubRoutine(currentBank, { mode: "incremental", horizon_hours: 24 });
      toast.success("Sub-routine queued");
      await refresh();
    } catch (error) {
      console.error("Failed to queue sub-routine:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const exportBrain = async () => {
    if (!currentBank) return;
    try {
      const blob = await client.exportBrainFile(currentBank);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${currentBank}.brain`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Brain snapshot exported");
    } catch (error) {
      console.error("Failed to export brain snapshot:", error);
    }
  };

  const handleImport = async (file: File) => {
    if (!currentBank) return;
    setIsLoading(true);
    setImportValidation("");
    try {
      const validation = await client.validateBrainImport(currentBank, file);
      if (!validation.valid) {
        setImportValidation(validation.reason || "Validation failed");
        return;
      }
      setImportValidation(`Valid schema version ${validation.version ?? "unknown"}`);
      await client.importBrainFile(currentBank, file);
      toast.success("Brain snapshot imported");
      await refresh();
    } catch (error) {
      console.error("Failed to import brain snapshot:", error);
      setImportValidation(error instanceof Error ? error.message : "Import failed");
    } finally {
      setIsLoading(false);
    }
  };

  const fetchRemoteBanks = async () => {
    if (!remoteEndpoint) return;
    setIsFetchingBanks(true);
    setRemoteBanks([]);
    try {
      const data = await client.fetchRemoteBanks({
        remote_endpoint: remoteEndpoint,
        remote_api_key: remoteApiKey || undefined,
      });
      const banks: Array<{ bank_id: string }> = data.banks ?? [];
      setRemoteBanks(banks);
      if (banks.length === 1) {
        setRemoteBankId(banks[0].bank_id);
      }
      if (banks.length === 0) {
        toast.error("No banks found on remote instance");
      }
    } catch (error) {
      console.error("Failed to fetch remote banks:", error);
      toast.error("Could not reach remote endpoint");
    } finally {
      setIsFetchingBanks(false);
    }
  };

  const learnFromRemote = async () => {
    if (!currentBank || !remoteEndpoint || !remoteBankId) return;
    setIsLearning(true);
    setLearnStatus("");
    try {
      const result = await client.learnFromRemoteBrain(currentBank, {
        remote_endpoint: remoteEndpoint,
        remote_bank_id: remoteBankId,
        remote_api_key: remoteApiKey || undefined,
        learning_type: learningType,
      });
      if (result.deduplicated) {
        setLearnStatus("Learning already in progress for this remote source.");
      } else {
        setLearnStatus(`Learning queued (operation: ${result.operation_id.slice(0, 8)}...)`);
        toast.success("Brain learning queued — knowledge transfer in progress");
      }
      setTimeout(() => void refresh(), 3000);
    } catch (error) {
      console.error("Failed to trigger brain learning:", error);
      setLearnStatus(error instanceof Error ? error.message : "Learning failed");
    } finally {
      setIsLearning(false);
    }
  };

  const probeRemote = async () => {
    if (!remoteEndpoint || !remoteBankId) return;
    setIsProbingRemote(true);
    try {
      const result = await client.probeRemoteCapabilities({
        remote_endpoint: remoteEndpoint,
        remote_bank_id: remoteBankId,
        remote_api_key: remoteApiKey || undefined,
      });
      setRemoteCapabilities(result);
      if (learningType === "auto") {
        setLearnStatus(`Probe complete. Recommended: ${result.recommended_learning_type}`);
      }
    } catch (error) {
      console.error("Failed to probe remote capabilities:", error);
      toast.error("Capability probe failed");
    } finally {
      setIsProbingRemote(false);
    }
  };

  useEffect(() => {
    if (currentBank) void refresh();
  }, [influenceEntityType, influenceTopK]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold mb-2 text-foreground">Brain</h1>
        <p className="text-muted-foreground">
          Operational visibility for `.brain` cache status, prediction profile, and brain-to-brain
          knowledge transfer.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button onClick={refresh} disabled={isLoading}>
          {isLoading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
          Refresh
        </Button>
        <Button onClick={runSubRoutine} variant="outline" disabled={isLoading}>
          Run Sub-Routine
        </Button>
        {importExportEnabled && (
          <>
            <Button onClick={exportBrain} variant="outline" disabled={isLoading}>
              <Download className="w-4 h-4 mr-2" />
              Export .brain
            </Button>
            <Button
              variant="outline"
              disabled={isLoading}
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="w-4 h-4 mr-2" />
              Import .brain
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".brain,.atulya,application/octet-stream"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void handleImport(file);
                event.target.value = "";
              }}
            />
          </>
        )}
        {currentBank && (
          <Button asChild variant="secondary">
            <Link href={`/banks/${currentBank}/brain-intelligence`}>Deep Dive</Link>
          </Button>
        )}
      </div>

      {influenceError && (
        <div className="text-xs text-amber-600 dark:text-amber-300 border border-amber-500/30 rounded-md px-3 py-2">
          Influence preview unavailable: {influenceError}
        </div>
      )}

      {influence && (
        <Card>
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-semibold text-foreground">Influence Snapshot (14d)</h2>
              <div className="flex items-center gap-2">
                <select
                  value={influenceEntityType}
                  onChange={(e) =>
                    setInfluenceEntityType(
                      e.target.value as "all" | "memory" | "chunk" | "mental_model"
                    )
                  }
                  className="rounded border border-input bg-background px-2 py-1 text-xs"
                >
                  <option value="all">all types</option>
                  <option value="memory">memory</option>
                  <option value="chunk">chunk</option>
                  <option value="mental_model">mental_model</option>
                </select>
                <select
                  value={String(influenceTopK)}
                  onChange={(e) => setInfluenceTopK(Number(e.target.value))}
                  className="rounded border border-input bg-background px-2 py-1 text-xs"
                >
                  <option value="5">top 5</option>
                  <option value="8">top 8</option>
                  <option value="12">top 12</option>
                  <option value="20">top 20</option>
                </select>
                <span className="text-xs text-muted-foreground">
                  top: {Number(influence.summary.top_influence || 0).toFixed(2)}
                </span>
              </div>
            </div>
            {Object.keys(influenceTypeCounts).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(influenceTypeCounts).map(([type, count]) => (
                  <span
                    key={type}
                    className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground"
                  >
                    {type}: {count}
                  </span>
                ))}
              </div>
            )}
            {influence.leaderboard.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Low signal: not enough retrieval activity yet. Run recall/retain cycles or trigger
                sub-routine and refresh.
              </p>
            ) : (
              <div className="grid gap-2 md:grid-cols-2">
                {influence.leaderboard.slice(0, influenceTopK).map((item) => (
                  <div key={item.id} className="rounded border border-border p-2">
                    <div className="text-xs text-muted-foreground">{item.type}</div>
                    <div className="text-sm font-medium text-foreground truncate">{item.text}</div>
                    <div className="text-xs text-muted-foreground">
                      influence {(item.influence_score * 100).toFixed(1)}% | accesses{" "}
                      {item.access_count}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <div className="text-xs text-muted-foreground mb-2">Access Heatmap</div>
                <div className="space-y-[2px]">
                  {miniHeatmapRows.map((row, dayIndex) => (
                    <div
                      key={`mini-row-${dayIndex}`}
                      className="grid gap-[2px]"
                      style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}
                    >
                      {row
                        .sort((a, b) => a.hour_utc - b.hour_utc)
                        .map((cell) => (
                          <div
                            key={`${cell.weekday}-${cell.hour_utc}`}
                            className="h-2 rounded-sm"
                            style={{
                              backgroundColor: `rgba(59,130,246,${Math.max(0.08, cell.score)})`,
                            }}
                            title={`day ${cell.weekday}, h${cell.hour_utc}: ${(cell.score * 100).toFixed(0)}%`}
                          />
                        ))}
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-2">EWMA Trend</div>
                <svg viewBox="0 0 240 48" className="w-full h-12">
                  {influence.trend.length > 1 && (
                    <polyline
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      points={influence.trend
                        .map(
                          (p, i) =>
                            `${(i / (influence.trend.length - 1)) * 240},${48 - p.ewma * 46}`
                        )
                        .join(" ")}
                    />
                  )}
                </svg>
                <p className="text-xs text-muted-foreground">
                  Smoothing uses EWMA for stable signal and anomaly-resistant trend reading.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {importValidation && (
        <div className="text-sm text-muted-foreground border border-border rounded-md px-3 py-2">
          {importValidation}
        </div>
      )}

      <Card>
        <CardContent className="p-4 space-y-2">
          <h2 className="font-semibold text-foreground">Runtime Status</h2>
          <p className="text-sm text-muted-foreground">
            cache: {status?.exists ? "ready" : "missing"} | native:{" "}
            {status?.native_library_loaded ? "loaded" : "fallback-python"} | circuit:{" "}
            {status?.circuit_open ? "open" : "closed"}
          </p>
          <p className="text-sm text-muted-foreground">
            size: {status?.size_bytes ?? 0} bytes | format: {status?.format_version ?? "n/a"} |
            model: {status?.model_signature ?? "n/a"}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4 space-y-2">
          <h2 className="font-semibold text-foreground">Prediction Timeline</h2>
          {predictions?.predictions?.length ? (
            <div className="flex flex-wrap gap-2">
              {predictions.predictions.map((item: { hour_utc: number; score: number }) => (
                <span
                  key={item.hour_utc}
                  className="inline-flex items-center rounded-full border border-indigo-500/30 px-2 py-0.5 text-xs text-indigo-600 dark:text-indigo-300"
                >
                  {item.hour_utc.toString().padStart(2, "0")}:00 UTC ({Math.round(item.score * 100)}
                  %)
                </span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No predictions available yet.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-foreground">24h Histogram</h2>
            <p className="text-xs text-muted-foreground">samples: {histogram?.sample_count ?? 0}</p>
          </div>
          {histogram?.histogram?.length ? (
            <div className="grid grid-cols-12 gap-1">
              {histogram.histogram.map((item: { hour_utc: number; score: number }) => {
                const height = Math.max(6, Math.round(item.score * 120));
                return (
                  <div key={item.hour_utc} className="flex flex-col items-center gap-1">
                    <div
                      className="w-full rounded-sm bg-red-500/80"
                      style={{ height: `${height}px` }}
                      title={`${item.hour_utc.toString().padStart(2, "0")}:00 UTC - ${Math.round(item.score * 100)}%`}
                    />
                    <span className="text-[10px] text-muted-foreground">
                      {item.hour_utc.toString().padStart(2, "0")}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No histogram available yet.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4 space-y-4">
          <div className="flex items-center gap-2">
            <Link2 className="w-5 h-5 text-foreground" />
            <h2 className="font-semibold text-foreground">Learn from Remote Brain</h2>
          </div>
          <p className="text-sm text-muted-foreground">
            Connect to another Atulya instance to distill its knowledge into this brain. Mental
            models, memories, and activity patterns will be merged and learned.
          </p>

          <div className="grid gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1">
                Remote API Endpoint
              </label>
              <div className="flex gap-2">
                <input
                  type="url"
                  placeholder="http://192.168.0.104:8888"
                  value={remoteEndpoint}
                  onChange={(e) => {
                    setRemoteEndpoint(e.target.value);
                    setRemoteBanks([]);
                    setRemoteBankId("");
                    setRemoteCapabilities(null);
                  }}
                  className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!remoteEndpoint || isFetchingBanks}
                  onClick={fetchRemoteBanks}
                  className="shrink-0"
                >
                  {isFetchingBanks ? <Loader2 className="w-4 h-4 animate-spin" /> : "Fetch Banks"}
                </Button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  Remote Bank ID
                </label>
                {remoteBanks.length > 0 ? (
                  <select
                    value={remoteBankId}
                    onChange={(e) => {
                      setRemoteBankId(e.target.value);
                      setRemoteCapabilities(null);
                    }}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <option value="">Select a bank...</option>
                    {remoteBanks.map((bank) => (
                      <option key={bank.bank_id} value={bank.bank_id}>
                        {bank.bank_id}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    placeholder="default"
                    value={remoteBankId}
                    onChange={(e) => {
                      setRemoteBankId(e.target.value);
                      setRemoteCapabilities(null);
                    }}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                )}
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  API Key (optional)
                </label>
                <input
                  type="password"
                  placeholder="Bearer token"
                  value={remoteApiKey}
                  onChange={(e) => {
                    setRemoteApiKey(e.target.value);
                    setRemoteCapabilities(null);
                  }}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  Learning Type
                </label>
                <select
                  value={learningType}
                  onChange={(e) => setLearningType(e.target.value as LearningType)}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="auto">auto (recommended)</option>
                  <option value="distilled">distilled (.brain export only)</option>
                  <option value="structured">structured (models + memories + entities)</option>
                  <option value="raw_mirror">raw_mirror (memories only)</option>
                </select>
              </div>
              <div className="flex items-end">
                <Button
                  variant="outline"
                  onClick={probeRemote}
                  disabled={!remoteEndpoint || !remoteBankId || isProbingRemote}
                  className="w-full"
                >
                  {isProbingRemote ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                  Probe Remote
                </Button>
              </div>
            </div>
            {remoteCapabilities && (
              <div className="text-xs text-muted-foreground border border-border rounded-md px-3 py-2">
                <div>
                  Capabilities: export={String(remoteCapabilities.capabilities.brain_export_ok)} |
                  models={String(remoteCapabilities.capabilities.mental_models_ok)} | memories=
                  {String(remoteCapabilities.capabilities.memories_ok)} | entities=
                  {String(remoteCapabilities.capabilities.entities_ok)}
                </div>
                <div>
                  Recommended learning type:{" "}
                  <span className="text-foreground font-medium">
                    {remoteCapabilities.recommended_learning_type}
                  </span>
                </div>
              </div>
            )}
          </div>

          <Button
            onClick={learnFromRemote}
            disabled={isLearning || !remoteEndpoint || !remoteBankId}
          >
            {isLearning ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Link2 className="w-4 h-4 mr-2" />
            )}
            Learn from Remote Brain
          </Button>

          {learnStatus && (
            <div className="text-sm text-muted-foreground border border-border rounded-md px-3 py-2">
              {learnStatus}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
