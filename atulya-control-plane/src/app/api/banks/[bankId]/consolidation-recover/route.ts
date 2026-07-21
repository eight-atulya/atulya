/**
 * consolidation-recover — recover failed consolidations in atulya.
 *
 * Atulya has no dedicated "recover" endpoint (hindsight does).
 * Best equivalent: read pending_consolidation from stats, then trigger a
 * fresh consolidation.  The UI's recover button will see retried_count > 0
 * when there was real pending work, prompting a toast.
 *
 * Causal chain:
 *   getAgentStats → pending_consolidation (= retried_count) →
 *   triggerConsolidation → { operation_id } →
 *   return { retried_count, operation_id }
 *
 * PCRM: replaced stub with real backend calls. Confidence: high — both SDK
 * methods verified in sdk.gen.ts.
 */

import { NextResponse } from "next/server";
import { sdk, createLowLevelClientForRequest } from "@/lib/atulya-client";

export async function POST(request: Request, { params }: { params: Promise<{ bankId: string }> }) {
  const { bankId } = await params;

  if (!bankId) {
    return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
  }

  try {
    // [branch] Step 1 — how many memories are waiting for consolidation?
    const statsResponse = await sdk.getAgentStats({
      client: createLowLevelClientForRequest(request),
      path: { bank_id: bankId },
    });

    const retriedCount: number =
      !statsResponse.error && statsResponse.data
        ? ((statsResponse.data as { pending_consolidation?: number }).pending_consolidation ?? 0)
        : 0;

    // [branch] Step 2 — trigger a fresh consolidation pass to recover them
    const consolidationResponse = await sdk.triggerConsolidation({
      client: createLowLevelClientForRequest(request),
      path: { bank_id: bankId },
    });

    if (consolidationResponse.error) {
      console.error("API error triggering consolidation recovery:", consolidationResponse.error);
      return NextResponse.json({ error: "Failed to trigger consolidation" }, { status: 500 });
    }

    const operationId =
      (consolidationResponse.data as { operation_id?: string } | undefined)?.operation_id ?? null;

    return NextResponse.json(
      { bank_id: bankId, retried_count: retriedCount, operation_id: operationId },
      { status: 200 }
    );
  } catch (error) {
    console.error("Error recovering consolidation:", error);
    return NextResponse.json({ error: "Failed to recover consolidation" }, { status: 500 });
  }
}
