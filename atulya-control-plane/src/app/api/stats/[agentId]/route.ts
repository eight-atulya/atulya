import { NextRequest, NextResponse } from "next/server";
import { sdk, lowLevelClient, DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ agentId: string }> }
) {
  try {
    const { agentId } = await params;

    // Fetch stats + operations in parallel
    const [statsResponse, opsRes] = await Promise.all([
      sdk.getAgentStats({ client: lowLevelClient, path: { bank_id: agentId } }),
      fetch(`${DATAPLANE_URL}/v1/default/banks/${agentId}/operations?limit=100`, {
        headers: getDataplaneHeaders(),
      }),
    ]);

    const statsData: Record<string, unknown> = { ...((statsResponse.data as object) ?? {}) };

    // Aggregate operations_by_status from real endpoint
    if (opsRes.ok) {
      const opsBody = await opsRes.json();
      const ops: Array<{ status: string }> = opsBody.operations ?? [];
      const byStatus: Record<string, number> = {};
      for (const op of ops) {
        byStatus[op.status] = (byStatus[op.status] ?? 0) + 1;
      }
      statsData.operations_by_status = byStatus;
    }

    return NextResponse.json(statsData, { status: 200 });
  } catch (error) {
    console.error("Error fetching stats:", error);
    return NextResponse.json({ error: "Failed to fetch stats" }, { status: 500 });
  }
}
