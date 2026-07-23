import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import { AdminMobileNav, AdminNav } from "@/components/admin-nav";
import { ControlPlaneShell } from "@/components/control-plane-shell";
import { WorkspaceSwitcher } from "@/components/workspace-switcher";
import { canUseAdminConsole, canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

export const metadata = { title: "Atulya Admin" };

const ORG_ITEMS = [
  { href: "/admin", label: "Overview", icon: "overview", action: "bank.read" },
  { href: "/admin/banks", label: "Memory banks", icon: "banks", action: "bank.read" },
  { href: "/admin/members", label: "Members", icon: "members", action: "admin.users" },
  {
    href: "/admin/service-accounts",
    label: "Service accounts",
    icon: "keys",
    action: "admin.keys",
  },
  { href: "/admin/roles", label: "Roles", icon: "roles", action: "admin.grants" },
  { href: "/admin/access", label: "Access", icon: "access", action: "admin.grants" },
  { href: "/admin/audit", label: "Audit", icon: "audit", action: "admin.audit" },
] as const;

const PLATFORM_ITEMS = [
  { href: "/admin/platform", label: "System health", icon: "health" },
  { href: "/admin/platform/organizations", label: "Organizations", icon: "organizations" },
  { href: "/admin/platform/tenants", label: "Bank inventory", icon: "banks" },
  { href: "/admin/platform/workers", label: "Workers", icon: "workers" },
  { href: "/admin/platform/operations", label: "Operations", icon: "operations" },
] as const;

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const identity = await getCurrentIdentity();
  if (!identity) redirect("/login?next=/admin");
  if (!canUseAdminConsole(identity)) redirect("/dashboard?access=denied");
  const platform = canUsePlatformAdmin(identity);
  const actions = new Set(identity.allowed_actions || []);
  const orgItems = identity.active_org_id
    ? ORG_ITEMS.filter((item) => actions.has(item.action))
    : [];

  return (
    <ControlPlaneShell
      variant="admin"
      topbar={
        <header className="flex h-full w-full items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <AdminMobileNav
              orgName={identity.org_name || "Platform"}
              orgItems={orgItems}
              platformItems={platform ? PLATFORM_ITEMS : []}
            />
            <WorkspaceSwitcher identity={identity} />
          </div>
          <div className="flex min-w-0 items-center gap-2">
            <Link
              href="/dashboard"
              className="flex h-8 items-center gap-1.5 rounded-md border border-highlight px-2.5 text-xs text-highlight transition-colors hover:bg-highlight hover:text-highlight-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-highlight"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Memory banks</span>
            </Link>
            <span className="inline-flex h-8 max-w-40 items-center truncate rounded-md border px-2.5 text-xs text-muted-foreground">
              {identity.display_name || identity.email}
            </span>
          </div>
        </header>
      }
      sidebar={
        <aside className="flex h-full min-h-0 w-60 flex-col overflow-hidden">
          <div className="flex h-16 items-center gap-3 border-b border-[var(--shell-border)] px-4">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary">
              <ShieldCheck className="h-4 w-4 text-primary-foreground" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">Administration</p>
              <p className="truncate text-[11px] text-muted-foreground">
                {identity.org_name || "Platform"}
              </p>
            </div>
          </div>
          {orgItems.length > 0 && (
            <>
              <p className="px-5 pb-1 pt-4 text-[10px] font-semibold uppercase text-muted-foreground">
                Workspace
              </p>
              <AdminNav items={orgItems} />
            </>
          )}
          {platform && (
            <>
              <p className="border-t px-5 pb-1 pt-4 text-[10px] font-semibold uppercase text-muted-foreground">
                Platform
              </p>
              <AdminNav items={PLATFORM_ITEMS} />
            </>
          )}
        </aside>
      }
      contentClassName="max-w-[1500px]"
    >
      {children}
    </ControlPlaneShell>
  );
}
