"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  CircleAlert,
  Database,
  LogOut,
  Moon,
  ShieldCheck,
  Sun,
  UserCircle,
} from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useBank } from "@/lib/bank-context";
import { useFeatures } from "@/lib/features-context";
import { useTheme } from "@/lib/theme-context";
import { cn } from "@/lib/utils";

type SessionInfo = {
  user: {
    display_name: string;
    role: string;
    identity_source: string;
  };
  auth: {
    mode: string;
    configured: boolean;
    logout_mode: "session" | "local";
  };
  tenancy: {
    provider: string;
    configured: boolean;
    supabase_url_configured: boolean;
    schema_prefix: string;
  };
  admin: {
    configured: boolean;
  };
  dataplane: {
    url: string;
  };
};

function StatusPill({ active, label }: { active: boolean; label: string }) {
  const Icon = active ? CheckCircle2 : CircleAlert;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
        active
          ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
          : "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300"
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border/60 py-2.5 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 truncate text-right text-sm font-medium text-foreground">
        {value}
      </span>
    </div>
  );
}

export function UserSettingsDialog() {
  const router = useRouter();
  const { currentBank, setCurrentBank, banks } = useBank();
  const { features } = useFeatures();
  const { theme, toggleTheme } = useTheme();
  const [open, setOpen] = React.useState(false);
  const [session, setSession] = React.useState<SessionInfo | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [loggingOut, setLoggingOut] = React.useState(false);

  React.useEffect(() => {
    if (!open || session) return;

    let cancelled = false;
    setLoading(true);
    fetch("/api/session")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<SessionInfo>;
      })
      .then((data) => {
        if (!cancelled) setSession(data);
      })
      .catch(() => {
        if (!cancelled) toast.error("Could not load settings");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, session]);

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setCurrentBank(null);
      for (const key of Object.keys(window.localStorage)) {
        if (key.startsWith("retain:draft:pending:")) {
          window.localStorage.removeItem(key);
        }
      }
      setOpen(false);
      toast.success("Signed out");
      router.replace("/login");
      router.refresh();
    } catch {
      toast.error("Could not sign out");
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          title="User settings"
          aria-label="Open user settings"
        >
          <UserCircle className="h-5 w-5" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[86vh] max-w-2xl overflow-hidden border-[var(--shell-border)] bg-background/92 p-0 shadow-2xl backdrop-blur-xl sm:rounded-[var(--shell-radius)]">
        <DialogHeader className="border-b border-border/70 px-6 py-5">
          <div className="flex items-start gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary-gradient text-white shadow-sm">
              <UserCircle className="h-6 w-6" />
            </div>
            <div className="min-w-0">
              <DialogTitle className="text-xl">Profile & Settings</DialogTitle>
              <DialogDescription className="mt-1">
                Control-plane profile, environment status, and session controls.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="max-h-[calc(86vh-7rem)] overflow-y-auto px-6 py-5">
          {loading && !session ? (
            <div className="rounded-lg border border-border bg-muted/30 p-4 text-sm text-muted-foreground">
              Loading settings...
            </div>
          ) : (
            <div className="space-y-5">
              <section className="rounded-lg border border-border/80 bg-card/55 p-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-semibold text-foreground">
                      {session?.user.display_name ?? "Control Plane Operator"}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {session?.user.role ?? "operator"} · {currentBank || "no bank selected"}
                    </p>
                  </div>
                  <StatusPill
                    active={Boolean(session?.auth.configured)}
                    label={session?.auth.configured ? "API auth" : "Public/local"}
                  />
                </div>
                <div className="mt-4">
                  <InfoRow label="Current bank" value={currentBank || "None"} />
                  <InfoRow label="Available banks" value={banks.length} />
                  <InfoRow
                    label="Identity source"
                    value={session?.user.identity_source ?? "local"}
                  />
                </div>
              </section>

              <section className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-border/80 bg-card/55 p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-primary" />
                    <p className="text-sm font-semibold">Access</p>
                  </div>
                  <InfoRow label="Auth mode" value={session?.auth.mode ?? "unknown"} />
                  <InfoRow
                    label="Admin"
                    value={session?.admin.configured ? "Configured" : "Not configured"}
                  />
                  <InfoRow
                    label="Logout"
                    value={
                      session?.auth.logout_mode === "session" ? "Session sign out" : "Local reset"
                    }
                  />
                </div>

                <div className="rounded-lg border border-border/80 bg-card/55 p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <Database className="h-4 w-4 text-primary" />
                    <p className="text-sm font-semibold">Tenancy</p>
                  </div>
                  <InfoRow label="Provider" value={session?.tenancy.provider ?? "unknown"} />
                  <InfoRow
                    label="Status"
                    value={session?.tenancy.configured ? "Configured" : "Default schema"}
                  />
                  <InfoRow label="Schema prefix" value={session?.tenancy.schema_prefix ?? "user"} />
                </div>
              </section>

              <section className="rounded-lg border border-border/80 bg-card/55 p-4">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-2">
                    {theme === "light" ? (
                      <Sun className="h-4 w-4 text-primary" />
                    ) : (
                      <Moon className="h-4 w-4 text-primary" />
                    )}
                    <div>
                      <p className="text-sm font-semibold">Appearance</p>
                      <p className="text-xs text-muted-foreground">
                        Use the current theme across the shell.
                      </p>
                    </div>
                  </div>
                  <Switch checked={theme === "dark"} onCheckedChange={toggleTheme} />
                </div>
              </section>

              <section className="rounded-lg border border-border/80 bg-card/55 p-4">
                <p className="text-sm font-semibold">System</p>
                <div className="mt-3">
                  <InfoRow label="Dataplane" value={session?.dataplane.url ?? "unknown"} />
                  <InfoRow
                    label="Brain runtime"
                    value={features?.brain_runtime ? "Enabled" : "Disabled"}
                  />
                  <InfoRow
                    label="File upload"
                    value={features?.file_upload_api ? "Enabled" : "Disabled"}
                  />
                </div>
              </section>

              <div className="flex flex-col gap-2 border-t border-border/70 pt-5 sm:flex-row sm:justify-end">
                <Button variant="outline" onClick={() => setOpen(false)}>
                  Close
                </Button>
                <Button
                  variant="destructive"
                  onClick={handleLogout}
                  disabled={loggingOut}
                  className="gap-2"
                >
                  <LogOut className="h-4 w-4" />
                  {loggingOut ? "Signing out..." : "Sign out"}
                </Button>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
