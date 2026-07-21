import { NextResponse } from "next/server";
import { canUseAdminConsole, canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

export async function GET() {
  const identity = await getCurrentIdentity();
  return NextResponse.json(
    {
      enabled: canUseAdminConsole(identity),
      organization_admin: canUseAdminConsole(identity),
      platform_admin: canUsePlatformAdmin(identity),
    },
    { status: identity ? 200 : 401 }
  );
}
