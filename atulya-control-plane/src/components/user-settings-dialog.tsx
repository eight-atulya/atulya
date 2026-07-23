"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  CircleAlert,
  Database,
  LogOut,
  MonitorSmartphone,
  Moon,
  ShieldCheck,
  Sun,
  Trash2,
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
    email: string | null;
    workspace: string | null;
    workspace_count: number;
  };
  auth: {
    mode: string;
    configured: boolean;
    logout_mode: "session" | "local";
    sessions: Array<{
      id: string;
      current: boolean;
      created_at: string;
      expires_at: string;
      last_used_at: string | null;
      ip_address: string | null;
      user_agent: string | null;
    }>;
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

const SETTINGS_NAV = [
  { id: "profile", label: "Profile", icon: UserCircle },
  { id: "access", label: "Access", icon: ShieldCheck },
  { id: "appearance", label: "Appearance", icon: Sun },
  { id: "sessions", label: "Sessions", icon: MonitorSmartphone },
  { id: "system", label: "System", icon: Database },
] as const;

type SettingsSection = (typeof SETTINGS_NAV)[number]["id"];

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
  const [activeSection, setActiveSection] = React.useState<SettingsSection>("profile");
  const settingsContentRef = React.useRef<HTMLDivElement>(null);

  const scrollToSection = (section: SettingsSection) => {
    const container = settingsContentRef.current;
    const target = container?.querySelector<HTMLElement>(`#settings-${section}`);
    if (!container || !target) return;

    const top =
      target.getBoundingClientRect().top -
      container.getBoundingClientRect().top +
      container.scrollTop -
      20;
    container.scrollTo({ top, behavior: "smooth" });
    setActiveSection(section);
  };

  const updateActiveSection = (event: React.UIEvent<HTMLDivElement>) => {
    const container = event.currentTarget;
    const threshold = container.getBoundingClientRect().top + 80;
    let nextSection: SettingsSection = "profile";

    for (const item of SETTINGS_NAV) {
      const target = container.querySelector<HTMLElement>(`#settings-${item.id}`);
      if (target && target.getBoundingClientRect().top <= threshold) {
        nextSection = item.id;
      }
    }

    setActiveSection(nextSection);
  };

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

  const revokeSession = async (sessionId: string, current: boolean) => {
    try {
      const response = await fetch(`/api/auth/sessions/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (current) {
        setOpen(false);
        router.replace("/login");
        router.refresh();
        return;
      }
      setSession((value) =>
        value
          ? {
              ...value,
              auth: {
                ...value.auth,
                sessions: value.auth.sessions.filter((item) => item.id !== sessionId),
              },
            }
          : value
      );
      toast.success("Session revoked");
    } catch {
      toast.error("Could not revoke session");
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
      <DialogContent className="w-[calc(100%-2rem)] max-h-[86vh] max-w-4xl overflow-hidden border-highlight bg-background/92 p-0 shadow-2xl backdrop-blur-xl sm:rounded-[var(--shell-radius)]">
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

        <div className="grid max-h-[calc(86vh-7rem)] min-h-0 md:grid-cols-[12rem_minmax(0,1fr)]">
          <nav
            aria-label="Settings sections"
            className="border-b border-border/70 px-3 py-3 md:border-b-0 md:border-r md:px-4 md:py-5"
          >
            <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Settings
            </p>
            <div className="flex gap-1 overflow-x-auto md:block md:space-y-1">
              {SETTINGS_NAV.map((item) => {
                const Icon = item.icon;
                const active = activeSection === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    aria-current={active ? "page" : undefined}
                    onClick={() => scrollToSection(item.id)}
                    className={cn(
                      "flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-left text-xs font-medium transition-colors md:w-full",
                      active
                        ? "bg-highlight text-highlight-foreground"
                        : "text-muted-foreground hover:bg-accent hover:text-foreground"
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {item.label}
                  </button>
                );
              })}
            </div>
          </nav>

          <div
            ref={settingsContentRef}
            onScroll={updateActiveSection}
            className="min-h-0 overflow-y-auto px-4 py-5 sm:px-6"
          >
            {loading && !session ? (
              <div className="rounded-lg border border-border bg-muted/30 p-4 text-sm text-muted-foreground">
                Loading settings...
              </div>
            ) : (
              <div className="space-y-5">
                <section
                  id="settings-profile"
                  className="scroll-mt-5 rounded-lg border border-border/80 bg-card/55 p-4"
                >
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
                    <InfoRow label="Workspace" value={session?.user.workspace ?? "None"} />
                    <InfoRow label="Active sessions" value={session?.auth.sessions.length ?? 0} />
                  </div>
                </section>

                <section id="settings-access" className="scroll-mt-5 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-lg border border-border/80 bg-card/55 p-4">
                    <div className="mb-3 flex items-center gap-2">
                      <ShieldCheck className="h-4 w-4 text-primary" />
                      <p className="text-sm font-semibold">Access</p>
                    </div>
                    <InfoRow label="Auth mode" value={session?.auth.mode ?? "unknown"} />
                    <InfoRow
                      label="Admin"
                      value={session?.admin.configured ? "Granted" : "Not granted"}
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
                    <InfoRow
                      label="Schema prefix"
                      value={session?.tenancy.schema_prefix ?? "user"}
                    />
                  </div>
                </section>

                <section
                  id="settings-appearance"
                  className="scroll-mt-5 rounded-lg border border-border/80 bg-card/55 p-4"
                >
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

                <section
                  id="settings-sessions"
                  className="scroll-mt-5 rounded-lg border border-border/80 bg-card/55 p-4"
                >
                  <div className="mb-3 flex items-center gap-2">
                    <MonitorSmartphone className="h-4 w-4 text-primary" />
                    <p className="text-sm font-semibold">Sessions</p>
                  </div>
                  <div className="divide-y rounded-md border">
                    {(session?.auth.sessions || []).map((item) => (
                      <div key={item.id} className="flex items-center gap-3 px-3 py-2.5">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="truncate text-xs font-medium">
                              {item.user_agent || "Unknown browser"}
                            </p>
                            {item.current && <StatusPill active label="Current" />}
                          </div>
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            {item.ip_address || "Unknown IP"} · Last used{" "}
                            {item.last_used_at
                              ? new Date(item.last_used_at).toLocaleString()
                              : new Date(item.created_at).toLocaleString()}
                          </p>
                        </div>
                        <Button
                          size="icon"
                          variant="ghost"
                          title={item.current ? "Sign out this session" : "Revoke session"}
                          onClick={() => void revokeSession(item.id, item.current)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    ))}
                    {!session?.auth.sessions.length && (
                      <p className="p-3 text-xs text-muted-foreground">No active sessions.</p>
                    )}
                  </div>
                </section>

                <section
                  id="settings-system"
                  className="scroll-mt-5 rounded-lg border border-border/80 bg-card/55 p-4"
                >
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
        </div>
      </DialogContent>
    </Dialog>
  );
}
