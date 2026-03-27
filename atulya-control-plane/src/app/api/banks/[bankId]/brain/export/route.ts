import { NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/atulya-client";

export async function GET(_: Request, { params }: { params: Promise<{ bankId: string }> }) {
  try {
    const { bankId } = await params;
    if (!bankId) {
      return NextResponse.json({ error: "bank_id is required" }, { status: 400 });
    }

    const response = await fetch(`${DATAPLANE_URL}/v1/default/banks/${bankId}/brain/export`, {
      method: "GET",
      headers: getDataplaneHeaders(),
    });

    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json(
        { error: errorText || "Failed to export brain snapshot" },
        { status: response.status }
      );
    }

    const bytes = await response.arrayBuffer();
    return new Response(bytes, {
      status: 200,
      headers: {
        "Content-Type": response.headers.get("Content-Type") || "application/octet-stream",
        "Content-Disposition":
          response.headers.get("Content-Disposition") || `attachment; filename="${bankId}.brain"`,
      },
    });
  } catch (error) {
    console.error("Error exporting brain snapshot:", error);
    return NextResponse.json({ error: "Failed to export brain snapshot" }, { status: 500 });
  }
}
