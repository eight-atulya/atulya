import { NextResponse } from "next/server";
import { createClient, createConfig, sdk } from "@eight-atulya/atulya-client";
import { getDataplaneHeaders } from "@/lib/atulya-client";

const HEALTH_CHECK_TIMEOUT_MS = 3000;

export async function GET() {
  const status: {
    status: string;
    service: string;
    dataplane?: {
      status: string;
      url: string;
      error?: string;
    };
  } = {
    status: "ok",
    service: "atulya-control-plane",
  };

  // Check dataplane connectivity with a short timeout
  const dataplaneUrl = process.env.ATULYA_CP_DATAPLANE_API_URL || "http://localhost:8888";
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), HEALTH_CHECK_TIMEOUT_MS);

    const healthClient = createClient(
      createConfig({
        baseUrl: dataplaneUrl,
        signal: controller.signal,
        headers: getDataplaneHeaders(),
      })
    );

    try {
      await sdk.listBanks({ client: healthClient });
      status.dataplane = {
        status: "connected",
        url: dataplaneUrl,
      };
    } finally {
      clearTimeout(timeoutId);
    }
  } catch (error) {
    let errorMessage = error instanceof Error ? error.message : String(error);
    if (error instanceof Error && error.name === "AbortError") {
      errorMessage = `Request timed out after ${HEALTH_CHECK_TIMEOUT_MS}ms`;
    }
    status.dataplane = {
      status: "disconnected",
      url: dataplaneUrl,
      error: errorMessage,
    };
  }

  return NextResponse.json(status, { status: 200 });
}
