import { NextRequest, NextResponse } from "next/server";

const DEFAULT_FIRECRAWL = "http://127.0.0.1:3002";
const DEFAULT_FIRECRAWL_API_KEY = "11111111-1111-4111-8111-111111111111";

function base(url: string): string {
  return url.replace(/\/$/, "");
}

/**
 * Server-side Firecrawl extraction proxy for URL-to-markdown previews.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const rawUrl = typeof body.url === "string" ? body.url.trim() : "";
    if (!rawUrl || !/^https?:\/\//i.test(rawUrl)) {
      return NextResponse.json({ error: "Valid http(s) url is required" }, { status: 400 });
    }

    const firecrawl = base(process.env.ATULYA_CP_INTERNET_FIRECRAWL_URL || DEFAULT_FIRECRAWL);
    const apiKey = process.env.ATULYA_API_CORTEX_FIRECRAWL_API_KEY || DEFAULT_FIRECRAWL_API_KEY;
    const maxChars = Math.min(8000, Math.max(400, parseInt(String(body.max_chars ?? 2200), 10) || 2200));

    const res = await fetch(`${firecrawl}/v0/scrape`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url: rawUrl, formats: ["markdown"] }),
      signal: AbortSignal.timeout(120_000),
    });

    if (!res.ok) {
      return NextResponse.json(
        { error: `Firecrawl HTTP ${res.status}`, detail: await res.text().catch(() => "") },
        { status: 502 }
      );
    }

    const payload = (await res.json()) as {
      success?: boolean;
      data?: { markdown?: string; content?: string };
    };
    if (!payload.success) {
      return NextResponse.json({ error: "Firecrawl extraction failed" }, { status: 502 });
    }

    const markdown = String(payload.data?.markdown || payload.data?.content || "");
    const truncated = markdown.length > maxChars;
    const bodyMd = truncated ? `${markdown.slice(0, maxChars)}\n\n...[truncated]` : markdown;

    return NextResponse.json({
      url: rawUrl,
      markdown: bodyMd,
      truncated,
      chars: bodyMd.length,
    });
  } catch (e) {
    console.error("[internet/extract]", e);
    return NextResponse.json({ error: "Extract failed (is Firecrawl up?)" }, { status: 503 });
  }
}

