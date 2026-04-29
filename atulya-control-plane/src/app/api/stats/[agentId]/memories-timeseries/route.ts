/**
 * memories-timeseries — derived from graph table_rows (mentioned_at + fact_type).
 *
 * Strategy: fetch graph endpoint (single call), bucket each table_row by
 * mentioned_at truncated to day/hour, count per fact_type (world/experience/observation).
 * Accurate because table_rows includes every retained memory node with full metadata.
 *
 * PCRM: switched from listOperations (items_count always 0) → graph table_rows.
 *       Root cause: operations endpoint path was /banks/{id}/operations (404),
 *       real path is /v1/default/banks/{id}/operations; and items_count=0 for all ops.
 */

import { NextRequest, NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

type TruncUnit = "hour" | "day";

/** How many buckets and what trunc to use for each period shorthand */
const PERIOD_CONFIG: Record<string, { trunc: TruncUnit; windowMs: number; buckets: number }> = {
  "1h": { trunc: "hour", windowMs: 60 * 60 * 1000, buckets: 12 },
  "12h": { trunc: "hour", windowMs: 12 * 60 * 60 * 1000, buckets: 12 },
  "1d": { trunc: "hour", windowMs: 24 * 60 * 60 * 1000, buckets: 24 },
  "7d": { trunc: "day", windowMs: 7 * 24 * 60 * 60 * 1000, buckets: 7 },
  "30d": { trunc: "day", windowMs: 30 * 24 * 60 * 60 * 1000, buckets: 30 },
  "90d": { trunc: "day", windowMs: 90 * 24 * 60 * 60 * 1000, buckets: 30 },
};

function truncateToUnit(date: Date, trunc: TruncUnit): Date {
  if (trunc === "hour") {
    return new Date(
      Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate(), date.getUTCHours())
    );
  }
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
}

function stepMs(trunc: TruncUnit): number {
  return trunc === "hour" ? 3_600_000 : 86_400_000;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ agentId: string }> }
) {
  const { agentId } = await params;
  const period = request.nextUrl.searchParams.get("period") || "7d";
  const config = PERIOD_CONFIG[period] ?? PERIOD_CONFIG["7d"];
  const { trunc, windowMs } = config;

  const now = Date.now();
  const windowStart = now - windowMs;

  try {
    // [root] Single graph call — table_rows has fact_type + mentioned_at per memory node.
    // limit=10000: graph default is 1000, no server-side max — use high ceiling to avoid
    // silent undercounting on large banks. Operations items_count=0 so ops are wrong source.
    const res = await fetch(`${DATAPLANE_URL}/v1/default/banks/${agentId}/graph?limit=10000`, {
      headers: getDataplaneHeaders(),
    });

    if (!res.ok) {
      return NextResponse.json({ bank_id: agentId, period, trunc, buckets: [] }, { status: 200 });
    }

    const body = await res.json();
    const rows: Array<{ mentioned_at?: string | null; fact_type?: string | null }> =
      body.table_rows ?? [];

    // Bucket by truncated mentioned_at, split by fact_type
    const bucketMap = new Map<string, { world: number; experience: number; observation: number }>();

    for (const row of rows) {
      const ts = row.mentioned_at ? Date.parse(row.mentioned_at) : NaN;
      if (Number.isNaN(ts) || ts < windowStart) continue;
      const key = truncateToUnit(new Date(ts), trunc).toISOString();
      const b = bucketMap.get(key) ?? { world: 0, experience: 0, observation: 0 };
      const ft = row.fact_type ?? "world";
      if (ft === "experience") b.experience += 1;
      else if (ft === "observation") b.observation += 1;
      else b.world += 1;
      bucketMap.set(key, b);
    }

    // Dense sequential bucket array — no gaps
    const startBucket = truncateToUnit(new Date(windowStart), trunc);
    const endBucket = truncateToUnit(new Date(now), trunc);
    const step = stepMs(trunc);
    const buckets: Array<{ time: string; world: number; experience: number; observation: number }> =
      [];
    for (let t = startBucket.getTime(); t <= endBucket.getTime(); t += step) {
      const key = new Date(t).toISOString();
      buckets.push({
        time: key,
        ...(bucketMap.get(key) ?? { world: 0, experience: 0, observation: 0 }),
      });
    }

    return NextResponse.json({ bank_id: agentId, period, trunc, buckets }, { status: 200 });
  } catch (error) {
    console.error("[timeseries] error:", error);
    return NextResponse.json({ bank_id: agentId, period, trunc, buckets: [] }, { status: 200 });
  }
}
