import { NextResponse } from "next/server";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function dataplaneErrorResponse(status: number, data: unknown, fallback: string) {
  const record = asRecord(data);
  const error =
    (typeof record?.detail === "string" && record.detail) ||
    (typeof record?.error === "string" && record.error) ||
    fallback;
  return NextResponse.json({ error, details: data }, { status });
}
