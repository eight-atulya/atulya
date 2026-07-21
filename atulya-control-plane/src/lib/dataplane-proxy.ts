import { DATAPLANE_URL, getDataplaneHeadersForRequest } from "@/lib/atulya-client";

type DataplaneFetchInit = RequestInit & {
  path: string;
  request: Request;
};

function buildUrl(path: string): string {
  const trimmedBase = DATAPLANE_URL.replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${trimmedBase}${normalizedPath}`;
}

export async function fetchDataplaneJson({ path, request, headers, ...init }: DataplaneFetchInit) {
  const response = await fetch(buildUrl(path), {
    ...init,
    cache: "no-store",
    headers: getDataplaneHeadersForRequest(request, {
      Accept: "application/json",
      ...(headers as Record<string, string> | undefined),
    }),
  });

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: text };
    }
  }

  return { status: response.status, ok: response.ok, data };
}
