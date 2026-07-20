import { Suspense } from "react";
import { ShieldCheck } from "lucide-react";
import { ControlPlaneShell } from "@/components/control-plane-shell";
import { LoginPanel } from "@/components/login-panel";

export const metadata = { title: "Sign in | Atulya Control Plane" };

export default function LoginPage() {
  const authDisabled = process.env.ATULYA_CP_AUTH_DISABLED === "true";

  return (
    <ControlPlaneShell
      variant="landing"
      topbar={
        <header className="flex h-full w-full items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary">
              <ShieldCheck className="h-4 w-4 text-primary-foreground" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">Atulya Control Plane</p>
              <p className="text-[10px] text-muted-foreground">Session access</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {authDisabled && (
              <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-600 dark:text-amber-300">
                auth disabled
              </span>
            )}
          </div>
        </header>
      }
      contentClassName="flex max-w-5xl items-start pt-8 sm:pt-12"
    >
      <div className="w-full">
        <section className="mx-auto min-w-0 max-w-xl">
          <Suspense fallback={<div className="h-80 rounded-lg border bg-card" />}>
            <LoginPanel />
          </Suspense>
        </section>
      </div>
    </ControlPlaneShell>
  );
}
