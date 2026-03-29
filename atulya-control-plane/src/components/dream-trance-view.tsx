"use client";

import { useEffect, useMemo, useState } from "react";
import { useBank } from "@/lib/bank-context";
import { client, type DreamArtifact, type DreamStats } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CopyButton } from "@/components/ui/copy-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type DreamConfig = {
  enabled: boolean;
  trance_enabled: boolean;
  trigger_mode: "event" | "cron" | "hybrid";
  cron_interval_minutes: number;
  cooldown_minutes: number;
  top_k: number;
  max_input_tokens: number;
  max_output_tokens: number;
  dream_experience: "hybrid" | "structured" | "narrative";
  prediction_horizon: "near" | "mixed" | "far";
  auto_write_posture: string;
  promotion_gate: string;
  worker_prompt: string;
  write_distilled_summary: boolean;
  distillation_mode: "off" | "summary" | "fragments";
  distillation_max_fragments: number;
  quality_threshold: number;
  min_recall_results: number;
  novelty_threshold: number;
  validation_lookback_days: number;
  max_pending_predictions: number;
  max_artifact_bytes: number;
  language_tone: string;
  enforce_layman: boolean;
  value_focus: { money: number; time: number; happiness: number };
  prompt_template_version: string;
  preset: "balanced_org" | "lean_local" | "risk_guard" | "exec_strategy";
};

const DEFAULT_DREAM_CONFIG: DreamConfig = {
  enabled: false,
  trance_enabled: false,
  trigger_mode: "hybrid",
  cron_interval_minutes: 180,
  cooldown_minutes: 60,
  top_k: 4,
  max_input_tokens: 900,
  max_output_tokens: 500,
  dream_experience: "hybrid",
  prediction_horizon: "mixed",
  auto_write_posture: "aggressive_proposals",
  promotion_gate: "human_review",
  worker_prompt:
    "Use an Assumption -> Audit -> Train -> What-if -> Value chain. Be plain-language, concise, and causal. Show why the pattern happened, what evidence supports it, how confidence can be improved next cycle, and the likely impact on time saved, money, and happiness.",
  write_distilled_summary: false,
  distillation_mode: "off",
  distillation_max_fragments: 3,
  quality_threshold: 0.65,
  min_recall_results: 2,
  novelty_threshold: 0.58,
  validation_lookback_days: 45,
  max_pending_predictions: 24,
  max_artifact_bytes: 24000,
  language_tone: "plain-layman",
  enforce_layman: true,
  value_focus: { money: 1, time: 1, happiness: 1 },
  prompt_template_version: "v3-evidence-foresight",
  preset: "balanced_org",
};

const DREAM_PRESET_OVERRIDES: Record<DreamConfig["preset"], Partial<DreamConfig>> = {
  balanced_org: {
    top_k: 4,
    min_recall_results: 2,
    max_input_tokens: 900,
    max_output_tokens: 520,
    cooldown_minutes: 60,
    quality_threshold: 0.66,
    novelty_threshold: 0.58,
    validation_lookback_days: 45,
    value_focus: { money: 1, time: 1, happiness: 1 },
  },
  lean_local: {
    top_k: 3,
    min_recall_results: 2,
    max_input_tokens: 640,
    max_output_tokens: 420,
    cooldown_minutes: 90,
    quality_threshold: 0.7,
    novelty_threshold: 0.64,
    validation_lookback_days: 30,
    enforce_layman: true,
    value_focus: { money: 0.8, time: 1.4, happiness: 0.8 },
  },
  risk_guard: {
    top_k: 5,
    min_recall_results: 3,
    max_input_tokens: 1100,
    max_output_tokens: 480,
    cooldown_minutes: 120,
    quality_threshold: 0.78,
    novelty_threshold: 0.66,
    validation_lookback_days: 60,
    enforce_layman: true,
    value_focus: { money: 0.9, time: 0.9, happiness: 1.2 },
  },
  exec_strategy: {
    top_k: 4,
    min_recall_results: 2,
    max_input_tokens: 1000,
    max_output_tokens: 440,
    cooldown_minutes: 45,
    quality_threshold: 0.68,
    novelty_threshold: 0.6,
    validation_lookback_days: 45,
    language_tone: "executive-plain",
    value_focus: { money: 1.5, time: 1.2, happiness: 0.7 },
  },
};

function applyDreamPreset(config: DreamConfig, preset: DreamConfig["preset"]): DreamConfig {
  const overrides = DREAM_PRESET_OVERRIDES[preset] || {};
  return {
    ...config,
    ...overrides,
    value_focus: {
      ...config.value_focus,
      ...(overrides.value_focus || {}),
    },
    preset,
  };
}

export function DreamTranceView() {
  const { currentBank: bankId } = useBank();
  const [base, setBase] = useState<DreamConfig>(DEFAULT_DREAM_CONFIG);
  const [draft, setDraft] = useState<DreamConfig>(DEFAULT_DREAM_CONFIG);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [stats, setStats] = useState<DreamStats | null>(null);
  const [artifacts, setArtifacts] = useState<DreamArtifact[]>([]);
  const [actingId, setActingId] = useState<string | null>(null);

  const dirty = useMemo(() => JSON.stringify(base) !== JSON.stringify(draft), [base, draft]);

  const load = async () => {
    if (!bankId) return;
    const [cfgResp, statsResp, artifactsResp] = await Promise.all([
      client.getBankConfig(bankId),
      client.getDreamStats(bankId).catch(() => null),
      client.listDreamArtifacts(bankId, 10).catch(() => ({ items: [] as DreamArtifact[] })),
    ]);
    const incoming = { ...DEFAULT_DREAM_CONFIG, ...(cfgResp.config?.dream || {}) } as DreamConfig;
    setBase(incoming);
    setDraft(incoming);
    setStats(statsResp);
    setArtifacts(artifactsResp.items);
  };

  useEffect(() => {
    void load();
  }, [bankId]);

  if (!bankId) return null;

  return (
    <div className="space-y-6">
      <Card className="p-4 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">Dream / Trance State</h3>
            <p className="text-sm text-muted-foreground">
              Generate compact, meaningful HTML insights from top recalls.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={triggering || !draft.enabled}
              onClick={async () => {
                setTriggering(true);
                try {
                  await client.triggerDreamGeneration(bankId, {
                    trigger_source: "manual",
                    run_type: "dream",
                  });
                  await load();
                } finally {
                  setTriggering(false);
                }
              }}
            >
              {triggering ? "Running..." : "Run now"}
            </Button>
            <Button
              size="sm"
              disabled={!dirty || saving}
              onClick={async () => {
                setSaving(true);
                try {
                  await client.updateBankConfig(bankId, { dream: draft });
                  setBase(draft);
                } finally {
                  setSaving(false);
                }
              }}
            >
              {saving ? "Saving..." : "Save changes"}
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ToggleRow
            label="Enable Dream Mode"
            checked={draft.enabled}
            onCheckedChange={(v) => setDraft((d) => ({ ...d, enabled: v }))}
          />
          <ToggleRow
            label="Enable Trance Cron"
            checked={draft.trance_enabled}
            onCheckedChange={(v) => setDraft((d) => ({ ...d, trance_enabled: v }))}
          />
          <NumberRow
            label="Top-K recalls"
            value={draft.top_k}
            onChange={(v) => setDraft((d) => ({ ...d, top_k: v }))}
          />
          <NumberRow
            label="Minimum recall results"
            value={draft.min_recall_results}
            onChange={(v) => setDraft((d) => ({ ...d, min_recall_results: v }))}
          />
          <NumberRow
            label="Cooldown (minutes)"
            value={draft.cooldown_minutes}
            onChange={(v) => setDraft((d) => ({ ...d, cooldown_minutes: v }))}
          />
          <NumberRow
            label="Cron interval (minutes)"
            value={draft.cron_interval_minutes}
            onChange={(v) => setDraft((d) => ({ ...d, cron_interval_minutes: v }))}
          />
          <NumberRow
            label="Quality threshold (0-1)"
            step="0.05"
            value={draft.quality_threshold}
            onChange={(v) => setDraft((d) => ({ ...d, quality_threshold: v }))}
          />
          <NumberRow
            label="Max input tokens"
            value={draft.max_input_tokens}
            onChange={(v) => setDraft((d) => ({ ...d, max_input_tokens: v }))}
          />
          <NumberRow
            label="Max output tokens"
            value={draft.max_output_tokens}
            onChange={(v) => setDraft((d) => ({ ...d, max_output_tokens: v }))}
          />
          <SelectRow
            label="Dream experience"
            value={draft.dream_experience}
            options={[
              { value: "hybrid", label: "Hybrid" },
              { value: "structured", label: "Structured" },
              { value: "narrative", label: "Narrative" },
            ]}
            onValueChange={(v) =>
              setDraft((d) => ({ ...d, dream_experience: v as DreamConfig["dream_experience"] }))
            }
          />
          <SelectRow
            label="Prediction horizon"
            value={draft.prediction_horizon}
            options={[
              { value: "near", label: "Near-term" },
              { value: "mixed", label: "Mixed horizons" },
              { value: "far", label: "Far horizon" },
            ]}
            onValueChange={(v) =>
              setDraft((d) => ({
                ...d,
                prediction_horizon: v as DreamConfig["prediction_horizon"],
              }))
            }
          />
          <NumberRow
            label="Max artifact bytes"
            value={draft.max_artifact_bytes}
            onChange={(v) => setDraft((d) => ({ ...d, max_artifact_bytes: v }))}
          />
          <ToggleRow
            label="Enforce layman language"
            checked={draft.enforce_layman}
            onCheckedChange={(v) => setDraft((d) => ({ ...d, enforce_layman: v }))}
          />
          <SelectRow
            label="Preset"
            value={draft.preset}
            options={[
              { value: "balanced_org", label: "Balanced Org" },
              { value: "lean_local", label: "Lean Local (small/local LLM)" },
              { value: "risk_guard", label: "Risk Guard (high confidence)" },
              { value: "exec_strategy", label: "Exec Strategy (value-focused)" },
            ]}
            onValueChange={(v) => setDraft((d) => applyDreamPreset(d, v as DreamConfig["preset"]))}
          />
          <InputRow
            label="Language tone"
            value={draft.language_tone}
            onChange={(v) => setDraft((d) => ({ ...d, language_tone: v }))}
          />
          <div className="space-y-2">
            <Label>Prompt template</Label>
            <div className="rounded-md border bg-muted/20 px-3 py-2 text-sm text-muted-foreground">
              {draft.prompt_template_version} (managed by the release template, not per-bank tuning)
            </div>
          </div>
          <NumberRow
            label="Value focus: money"
            step="0.1"
            value={draft.value_focus.money}
            onChange={(v) =>
              setDraft((d) => ({ ...d, value_focus: { ...d.value_focus, money: v } }))
            }
          />
          <NumberRow
            label="Value focus: time"
            step="0.1"
            value={draft.value_focus.time}
            onChange={(v) =>
              setDraft((d) => ({ ...d, value_focus: { ...d.value_focus, time: v } }))
            }
          />
          <NumberRow
            label="Value focus: happiness"
            step="0.1"
            value={draft.value_focus.happiness}
            onChange={(v) =>
              setDraft((d) => ({ ...d, value_focus: { ...d.value_focus, happiness: v } }))
            }
          />
          <NumberRow
            label="Novelty threshold"
            step="0.05"
            value={draft.novelty_threshold}
            onChange={(v) => setDraft((d) => ({ ...d, novelty_threshold: v }))}
          />
          <NumberRow
            label="Validation lookback days"
            value={draft.validation_lookback_days}
            onChange={(v) => setDraft((d) => ({ ...d, validation_lookback_days: v }))}
          />
          <NumberRow
            label="Max pending predictions"
            value={draft.max_pending_predictions}
            onChange={(v) => setDraft((d) => ({ ...d, max_pending_predictions: v }))}
          />
        </div>
        <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
          Promotion policy is fixed for production safety: dreams generate aggressive proposal
          candidates, and durable write-back always requires explicit human review.
        </div>
        <div className="space-y-2">
          <Label>Worker prompt</Label>
          <Textarea
            rows={4}
            value={draft.worker_prompt}
            onChange={(e) => setDraft((d) => ({ ...d, worker_prompt: e.target.value }))}
          />
        </div>
      </Card>

      <Card className="p-4">
        <h4 className="font-semibold mb-2">Stats</h4>
        <div className="grid gap-2 text-sm text-muted-foreground md:grid-cols-2 xl:grid-cols-3">
          <div>runs={stats?.total_runs ?? 0}</div>
          <div>avg_quality={(stats?.avg_quality ?? 0).toFixed(2)}</div>
          <div>avg_novelty={(stats?.avg_novelty ?? 0).toFixed(2)}</div>
          <div>avg_tokens={(stats?.avg_tokens ?? 0).toFixed(0)}</div>
          <div>prediction_confirmation={(stats?.prediction_confirmation_rate ?? 0).toFixed(2)}</div>
          <div>unresolved_backlog={stats?.unresolved_prediction_backlog ?? 0}</div>
          <div>failed_runs={stats?.failed_run_count ?? 0}</div>
          <div>duplicate_suppressed={stats?.duplicate_suppression_count ?? 0}</div>
        </div>
      </Card>

      <Card className="p-4 space-y-3">
        <h4 className="font-semibold">Recent Dream Runs</h4>
        {artifacts.length === 0 && (
          <p className="text-sm text-muted-foreground">No dream runs yet.</p>
        )}
        {artifacts.map((a) => (
          <div key={a.run_id} className="border rounded-md p-3 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-xs text-muted-foreground">
                {a.created_at} | {a.run_type} | {a.status} | {a.maturity_tier} | q=
                {(a.quality_score ?? 0).toFixed(2)} | novelty={(a.novelty_score ?? 0).toFixed(2)}
                {a.legacy_run ? " | legacy" : ""}
              </div>
              <DreamStatusPill status={a.status} />
            </div>

            {a.summary && (
              <div className="rounded-md border bg-muted/20 p-3">
                <div className="mb-2 flex items-start justify-between gap-3">
                  <div className="text-sm font-medium">Summary</div>
                  <CopyButton text={a.summary} />
                </div>
                <p className="text-sm">{a.summary}</p>
              </div>
            )}

            {a.failure_reason && (
              <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-700 dark:text-red-300">
                {a.failure_reason}
              </div>
            )}

            {a.narrative_html && (
              <iframe
                title={`dream-${a.run_id}`}
                sandbox="allow-same-origin"
                srcDoc={a.narrative_html}
                className="h-52 w-full rounded border"
              />
            )}

            {!a.legacy_run && (
              <div className="grid gap-3 xl:grid-cols-2">
                <RunSection
                  title="Signals"
                  items={[
                    ...(a.signals?.hypotheses || []).map((item: string) => `Hypothesis: ${item}`),
                    ...(a.signals?.candidate_state_changes || []).map(
                      (item: string) => `State change: ${item}`
                    ),
                    ...(a.signals?.risks || []).map((item: string) => `Risk: ${item}`),
                    ...(a.signals?.opportunities || []).map(
                      (item: string) => `Opportunity: ${item}`
                    ),
                    ...(a.signals?.recommended_validations || []).map(
                      (item: string) => `Validate: ${item}`
                    ),
                  ]}
                />
                <RunSection
                  title="Evidence Basis"
                  items={[
                    `evidence_count=${a.evidence_basis?.evidence_count ?? 0}`,
                    `recurring_entities=${(a.evidence_basis?.recurring_entities || []).join(", ") || "none"}`,
                    `recurring_themes=${(a.evidence_basis?.recurring_themes || []).join(", ") || "none"}`,
                    `contradictions=${(a.evidence_basis?.contradictions || []).join(" | ") || "none"}`,
                    `graph_signals=${(a.evidence_basis?.graph_signals || []).join(" | ") || "none"}`,
                    `backlog=${a.evidence_basis?.unresolved_prediction_backlog ?? 0}`,
                  ]}
                />
              </div>
            )}

            {!a.legacy_run && a.predictions.length > 0 && (
              <div className="space-y-2">
                <div className="text-sm font-medium">Predictions</div>
                {a.predictions.map((prediction) => (
                  <div
                    key={prediction.prediction_id ?? prediction.title}
                    className="rounded-md border p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-sm font-medium">{prediction.title}</div>
                      <div className="text-xs text-muted-foreground">
                        {prediction.horizon} | {prediction.status} | c=
                        {(prediction.confidence ?? 0).toFixed(2)}
                      </div>
                    </div>
                    <p className="mt-2 text-sm text-muted-foreground">{prediction.description}</p>
                    {prediction.success_criteria.length > 0 && (
                      <div className="mt-2 text-xs text-muted-foreground">
                        Validate with: {prediction.success_criteria.join(" | ")}
                      </div>
                    )}
                    {prediction.prediction_id && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={actingId === prediction.prediction_id}
                          onClick={async () => {
                            setActingId(prediction.prediction_id!);
                            try {
                              await client.updateDreamPredictionOutcome(
                                bankId,
                                prediction.prediction_id!,
                                {
                                  status: "confirmed",
                                }
                              );
                              await load();
                            } finally {
                              setActingId(null);
                            }
                          }}
                        >
                          Confirm
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={actingId === prediction.prediction_id}
                          onClick={async () => {
                            setActingId(prediction.prediction_id!);
                            try {
                              await client.updateDreamPredictionOutcome(
                                bankId,
                                prediction.prediction_id!,
                                {
                                  status: "contradicted",
                                }
                              );
                              await load();
                            } finally {
                              setActingId(null);
                            }
                          }}
                        >
                          Contradict
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={actingId === prediction.prediction_id}
                          onClick={async () => {
                            setActingId(prediction.prediction_id!);
                            try {
                              await client.updateDreamPredictionOutcome(
                                bankId,
                                prediction.prediction_id!,
                                {
                                  status: "request_more_evidence",
                                }
                              );
                              await load();
                            } finally {
                              setActingId(null);
                            }
                          }}
                        >
                          Need More Evidence
                        </Button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {!a.legacy_run && a.growth_hypotheses.length > 0 && (
              <RunSection
                title="Growth / Consciousness"
                items={a.growth_hypotheses.map(
                  (item) =>
                    `${item.title}: ${item.description}${item.blind_spot ? ` | blind spot: ${item.blind_spot}` : ""}`
                )}
              />
            )}

            {!a.legacy_run && a.promotion_proposals.length > 0 && (
              <div className="space-y-2">
                <div className="text-sm font-medium">Proposed Promotions</div>
                {a.promotion_proposals.map((proposal) => (
                  <div
                    key={proposal.proposal_id ?? proposal.title}
                    className="rounded-md border p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-sm font-medium">
                        {proposal.title}{" "}
                        <span className="text-xs text-muted-foreground">
                          ({proposal.proposal_type})
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {proposal.review_status} | c={(proposal.confidence ?? 0).toFixed(2)}
                      </div>
                    </div>
                    <div className="mt-2 flex items-start justify-between gap-3">
                      <p className="text-sm text-muted-foreground">{proposal.content}</p>
                      <CopyButton text={proposal.content} />
                    </div>
                    {proposal.proposal_id && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={actingId === proposal.proposal_id}
                          onClick={async () => {
                            setActingId(proposal.proposal_id!);
                            try {
                              await client.reviewDreamProposal(bankId, proposal.proposal_id!, {
                                action: "approve",
                              });
                              await load();
                            } finally {
                              setActingId(null);
                            }
                          }}
                        >
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={actingId === proposal.proposal_id}
                          onClick={async () => {
                            setActingId(proposal.proposal_id!);
                            try {
                              await client.reviewDreamProposal(bankId, proposal.proposal_id!, {
                                action: "reject",
                              });
                              await load();
                            } finally {
                              setActingId(null);
                            }
                          }}
                        >
                          Reject
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={actingId === proposal.proposal_id}
                          onClick={async () => {
                            setActingId(proposal.proposal_id!);
                            try {
                              await client.reviewDreamProposal(bankId, proposal.proposal_id!, {
                                action: "request_more_evidence",
                              });
                              await load();
                            } finally {
                              setActingId(null);
                            }
                          }}
                        >
                          Need More Evidence
                        </Button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {!a.legacy_run && a.validation_outcomes.length > 0 && (
              <RunSection
                title="Validation Outcomes"
                items={a.validation_outcomes.map(
                  (item) => `${item.status}: ${item.note || "No note provided"}`
                )}
              />
            )}
          </div>
        ))}
      </Card>
    </div>
  );
}

function InputRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      <Input value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function SelectRow({
  label,
  value,
  onValueChange,
  options,
}: {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function ToggleRow({
  label,
  checked,
  onCheckedChange,
}: {
  label: string;
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between border rounded-md p-3">
      <Label>{label}</Label>
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
}

function NumberRow({
  label,
  value,
  onChange,
  step,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: string;
}) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      <Input
        type="number"
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value || 0))}
      />
    </div>
  );
}

function DreamStatusPill({ status }: { status: DreamArtifact["status"] }) {
  const tone =
    status === "success"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : status === "failed_llm" || status === "failed_validation"
        ? "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300"
        : status === "duplicate_low_novelty"
          ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
          : "border-slate-500/30 bg-slate-500/10 text-slate-700 dark:text-slate-300";
  return (
    <span className={`rounded-full border px-2 py-1 text-[11px] font-medium ${tone}`}>
      {status}
    </span>
  );
}

function RunSection({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 text-sm font-medium">{title}</div>
      <div className="space-y-1 text-sm text-muted-foreground">
        {items.map((item) => (
          <div key={`${title}-${item}`}>{item}</div>
        ))}
      </div>
    </div>
  );
}
