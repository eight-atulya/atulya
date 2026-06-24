/** Data Forge UI templates and domain profile helpers */

export type ForgeSourceType = "scenario" | "chat" | "timeseries" | "bank_only";

export interface ForgeDomainProfile {
  id: string;
  title: string;
  description: string;
}

export interface ForgeRecipeMeta {
  recipe_id: string;
  title: string;
  description?: string;
  requires_ingest?: boolean;
  cost_tier?: string;
  training_signal?: string;
}

export interface ForgeExporterMeta {
  adapter_id: string;
  title: string;
  description?: string;
}

export interface ForgeStage {
  id: string;
  label: string;
}

export const FORGE_SOURCE_LABELS: Record<ForgeSourceType, string> = {
  scenario: "Scenario seeds",
  chat: "Chat / conversations",
  timeseries: "Time-series / CSV rows",
  bank_only: "Use existing bank memories",
};

export const SCENARIO_TEMPLATE = {
  source_type: "scenario",
  payload: {
    scenarios: [
      {
        id: "demo-1",
        title: "Deploy region moved after latency complaints",
        query: "Where should the analytics worker be deployed now?",
        facts: [
          { id: "f1", key: "deploy_region", value: "us-east-1", timestamp: "2026-01-05T09:00:00Z" },
          {
            id: "f2",
            key: "deploy_region",
            value: "eu-west-1",
            timestamp: "2026-02-03T09:00:00Z",
            supersedes: ["f1"],
          },
        ],
        expected: { answer: "eu-west-1" },
      },
    ],
  },
};

export const CHAT_TEMPLATE = {
  source_type: "chat",
  payload: {
    context: "Customer support thread",
    sessions: [
      {
        session_id: "support-1",
        event_date: "2026-01-10T14:00:00Z",
        turns: [
          { role: "user", content: "Our API latency spiked in us-east-1 last week." },
          { role: "assistant", content: "I'll note the incident and check recent deploy changes." },
          { role: "user", content: "We moved the worker to eu-west-1 on Feb 3." },
        ],
      },
    ],
  },
};

export const TIMESERIES_TEMPLATE = {
  source_type: "timeseries",
  payload: {
    context: "Macro indicators",
    rows: [
      { key: "us_gdp_growth", value: "2.1%", timestamp: "2026-01-01", unit: "YoY" },
      { key: "fed_funds_rate", value: "4.50%", timestamp: "2026-01-15" },
      { key: "us_gdp_growth", value: "2.4%", timestamp: "2026-02-01", unit: "YoY" },
    ],
  },
};

export const BANK_ONLY_SOURCE = {
  source_type: "bank_only",
  payload: {},
};

export function sourceTemplate(type: ForgeSourceType): object {
  switch (type) {
    case "scenario":
      return SCENARIO_TEMPLATE;
    case "chat":
      return CHAT_TEMPLATE;
    case "timeseries":
      return TIMESERIES_TEMPLATE;
    case "bank_only":
      return BANK_ONLY_SOURCE;
  }
}

export function validateSourceJson(
  text: string
): { ok: true; value: object } | { ok: false; error: string } {
  if (!text.trim()) {
    return { ok: false, error: "Source payload is empty." };
  }
  try {
    const parsed = JSON.parse(text) as object;
    if (!parsed || typeof parsed !== "object") {
      return { ok: false, error: "Source must be a JSON object." };
    }
    const record = parsed as Record<string, unknown>;
    if (!record.source_type || typeof record.source_type !== "string") {
      return {
        ok: false,
        error: "Missing source_type (scenario, chat, timeseries, or bank_only).",
      };
    }
    return { ok: true, value: parsed };
  } catch {
    return { ok: false, error: "Invalid JSON — check commas, quotes, and brackets." };
  }
}

export function costTierLabel(tier?: string): string {
  switch (tier) {
    case "low":
      return "Low cost";
    case "high":
      return "Higher LLM cost";
    default:
      return "Medium cost";
  }
}

export function formatPassRate(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}
