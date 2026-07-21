import { NextRequest } from "next/server";
import { publicAuthProxy } from "@/lib/public-auth-proxy";

export function POST(request: NextRequest) {
  return publicAuthProxy(request, "/v1/auth/reset-password");
}
