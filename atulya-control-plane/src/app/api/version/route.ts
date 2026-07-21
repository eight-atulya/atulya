import { NextResponse } from "next/server";
import { createClient, createConfig, sdk } from "@eight-atulya/atulya-client";
import { DATAPLANE_URL } from "@/lib/atulya-client";

export async function GET() {
  try {
    const response = await sdk.getVersion({
      client: createClient(createConfig({ baseUrl: DATAPLANE_URL })),
    });

    if (response.error) {
      console.error("API error getting version:", response.error);
      return NextResponse.json({ error: "Failed to get version" }, { status: 500 });
    }

    return NextResponse.json(response.data, { status: 200 });
  } catch (error) {
    console.error("Error getting version:", error);
    return NextResponse.json({ error: "Failed to get version" }, { status: 500 });
  }
}
