import { NextRequest, NextResponse } from "next/server";

const ATULYA_SESSION_COOKIE = "atulya_session";
const ATULYA_LOGGED_OUT_COOKIE = "atulya_logged_out";
const PROTECTED_PREFIXES = ["/dashboard", "/banks", "/admin"];

export function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  const protectedRoute = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
  if (!protectedRoute) return NextResponse.next();

  const hasSession = Boolean(request.cookies.get(ATULYA_SESSION_COOKIE)?.value);
  const explicitlyLoggedOut = Boolean(request.cookies.get(ATULYA_LOGGED_OUT_COOKIE)?.value);
  const authDisabled = process.env.ATULYA_CP_AUTH_DISABLED === "true";
  const hasDevKey = pathname.startsWith("/admin")
    ? false
    : !explicitlyLoggedOut && Boolean(process.env.ATULYA_CP_DATAPLANE_API_KEY?.trim());
  if (hasSession || hasDevKey || authDisabled) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", pathname);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/dashboard/:path*", "/banks/:path*", "/admin/:path*"],
};
