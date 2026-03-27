"use client";

import { useEffect, useMemo, useState } from "react";
import { useBank } from "@/lib/bank-context";
import { client, type DreamArtifact, type DreamStats } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
  worker_prompt: string;
  write_distilled_summary: boolean;
  distillation_mode: "off" | "summary" | "fragments";
  distillation_max_fragments: number;
  quality_threshold: number;
  min_recall_results: number;
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
  max_output_tokens: 300,
  worker_prompt:
    "Use an Assumption -> Audit -> Train -> What-if -> Value chain. Be plain-language, concise, and causal. Show why the pattern happened, what evidence supports it, how confidence can be improved next cycle, and the likely impact on time saved, money, and happiness.",
  write_distilled_summary: false,
  distillation_mode: "off",
  distillation_max_fragments: 3,
  quality_threshold: 0.65,
  min_recall_results: 2,
  max_artifact_bytes: 24000,
  language_tone: "plain-layman",
  enforce_layman: true,
  value_focus: { money: 1, time: 1, happiness: 1 },
  prompt_template_version: "v2-causal-chain",
  preset: "balanced_org",
};

export function DreamTranceView() {
  const { currentBank: bankId } = useBank();
  const [base, setBase] = useState<DreamConfig>(DEFAULT_DREAM_CONFIG);
  const [draft, setDraft] = useState<DreamConfig>(DEFAULT_DREAM_CONFIG);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [stats, setStats] = useState<DreamStats | null>(null);
  const [artifacts, setArtifacts] = useState<DreamArtifact[]>([]);

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
          <NumberRow
            label="Max artifact bytes"
            value={draft.max_artifact_bytes}
            onChange={(v) => setDraft((d) => ({ ...d, max_artifact_bytes: v }))}
          />
          <ToggleRow
            label="Write distilled summary"
            checked={draft.write_distilled_summary}
            onCheckedChange={(v) => setDraft((d) => ({ ...d, write_distilled_summary: v }))}
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
            onValueChange={(v) => setDraft((d) => ({ ...d, preset: v as DreamConfig["preset"] }))}
          />
          <SelectRow
            label="Distillation mode"
            value={draft.distillation_mode}
            options={[
              { value: "off", label: "Off" },
              { value: "summary", label: "Summary" },
              { value: "fragments", label: "Fragments" },
            ]}
            onValueChange={(v) =>
              setDraft((d) => ({ ...d, distillation_mode: v as DreamConfig["distillation_mode"] }))
            }
          />
          {draft.distillation_mode === "fragments" && (
            <NumberRow
              label="Distillation fragments max"
              value={draft.distillation_max_fragments}
              onChange={(v) => setDraft((d) => ({ ...d, distillation_max_fragments: v }))}
            />
          )}
          <InputRow
            label="Language tone"
            value={draft.language_tone}
            onChange={(v) => setDraft((d) => ({ ...d, language_tone: v }))}
          />
          <InputRow
            label="Prompt template version"
            value={draft.prompt_template_version}
            onChange={(v) => setDraft((d) => ({ ...d, prompt_template_version: v }))}
          />
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
        <div className="text-sm text-muted-foreground">
          runs={stats?.total_runs ?? 0} | avg_quality={(stats?.avg_quality ?? 0).toFixed(2)} |
          avg_tokens=
          {(stats?.avg_tokens ?? 0).toFixed(0)} | distill_pass=
          {(stats?.distillation_pass_rate ?? 0).toFixed(2)}
        </div>
      </Card>

      <Card className="p-4 space-y-3">
        <h4 className="font-semibold">Recent Dream Artifacts</h4>
        {artifacts.length === 0 && (
          <p className="text-sm text-muted-foreground">No dream artifacts yet.</p>
        )}
        {artifacts.map((a) => (
          <div key={a.id} className="border rounded-md p-3 space-y-2">
            <div className="text-xs text-muted-foreground">
              {a.created_at} | {a.run_type} | q={a.quality_score.toFixed(2)} | distilled=
              {a.distilled_written ? "yes" : "no"}
            </div>
            <iframe
              title={`dream-${a.id}`}
              sandbox="allow-same-origin"
              srcDoc={a.html_blob}
              className="w-full h-44 rounded border"
            />
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
