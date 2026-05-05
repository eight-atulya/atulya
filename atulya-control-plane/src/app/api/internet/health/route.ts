import { NextResponse } from "next/server";

const DEFAULT_SEARXNG = "http://127.0.0.1:18080";
const DEFAULT_FIRECRAWL = "http://127.0.0.1:3002";

function base(url: string): string {
  return url.replace(/\/$/, "");
}

/**
 * Probe optional internet backends from the control plane server (no secrets exposed to browser).
 */
export async function GET() {
  const searxng = base(process.env.ATULYA_CP_INTERNET_SEARXNG_URL || DEFAULT_SEARXNG);
  const firecrawl = base(process.env.ATULYA_CP_INTERNET_FIRECRAWL_URL || DEFAULT_FIRECRAWL);

  const [searxngOk, firecrawlOk] = await Promise.all([
    fetch(`${searxng}/`, { method: "GET", signal: AbortSignal.timeout(5000) })
      .then((r) => r.ok)
      .catch(() => false),
    fetch(`${firecrawl}/v0/health/liveness`, { method: "GET", signal: AbortSignal.timeout(5000) })
      .then((r) => r.ok)
      .catch(() => false),
  ]);

  return NextResponse.json({
    searxng: { ok: searxngOk, base_url: searxng },
    firecrawl: { ok: firecrawlOk, base_url: firecrawl },
  });
}
