/**
 * GET /api/admin-access
 *
 * Server-side check: returns { enabled: true } if ATULYA_CP_ADMIN_API_KEY
 * is configured. NEVER returns the key value — only its presence.
 *
 * Used by the AdminButton client component to decide whether to redirect
 * or show an "access not configured" toast.
 *
 */

import { NextResponse } from "next/server";

export async function GET() {
  const enabled = Boolean(process.env.ATULYA_CP_ADMIN_API_KEY?.trim());
  return NextResponse.json({ enabled }, { status: 200 });
}
