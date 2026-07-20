/**
 * Admin section layout — server component.
 *
 * Guards access: if ATULYA_CP_ADMIN_API_KEY is not set → 404 (not 403,
 * to avoid route enumeration). Admin key is NEVER forwarded to the client.
 */

import { notFound, redirect } from "next/navigation";
import Link from "next/link";
import {
  Activity,
  ArrowLeft,
  Building2,
  Cpu,
  KeyRound,
  ListOrdered,
  ShieldCheck,
  UserRoundX,
} from "lucide-react";
import { ControlPlaneShell } from "@/components/control-plane-shell";
import { Button } from "@/components/ui/button";
import { isAdminConfigured } from "@/lib/admin-api";
import { canUseAdminConsole, canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

export const metadata = { title: "Atulya Admin" };

const NAV_ITEMS = [
  { href: "/admin", label: "System", icon: Activity },
  { href: "/admin/tenants", label: "Tenants", icon: Building2 },
  { href: "/admin/workers", label: "Workers", icon: Cpu },
  { href: "/admin/operations", label: "Operations", icon: ListOrdered },
  { href: "/admin/api-keys", label: "Access", icon: KeyRound },
];
const ORG_NAV_ITEMS = [{ href: "/admin/api-keys", label: "Access", icon: KeyRound }];

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  if (!isAdminConfigured()) notFound();
  const identity = await getCurrentIdentity();
  if (!identity) redirect("/login?next=/admin");

  const identityLabel = identity.display_name || identity.email || identity.role;
  if (!canUseAdminConsole(identity)) {
    return (
      <ControlPlaneShell
        variant="admin"
        topbar={
          <header className="flex h-full w-full items-center justify-between gap-4">
            <p className="text-xs font-medium text-muted-foreground">Organization Admin</p>
            <Link
              href="/dashboard"
              className="flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to memory banks
            </Link>
          </header>
        }
        contentClassName="max-w-3xl"
      >
        <div className="mx-auto mt-10 max-w-xl rounded-lg border bg-card p-6 shadow-sm">
          <div className="flex items-start gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-muted">
              <UserRoundX className="h-5 w-5 text-muted-foreground" />
            </div>
            <div className="min-w-0">
              <h1 className="text-lg font-semibold">Organization admin access required</h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Your account is signed in, but it cannot manage users, keys, or grants for this
                organization.
              </p>
              <div className="mt-4 rounded-md border bg-muted/30 px-3 py-2 text-sm">
                <span className="text-muted-foreground">Signed in as </span>
                <span className="font-medium">
                  {identity.email || identity.display_name || "current user"}
                </span>
                <span className="text-muted-foreground"> with role </span>
                <span className="font-medium">{identity.role}</span>
              </div>
              <Button asChild className="mt-5">
                <Link href="/dashboard">Back to memory banks</Link>
              </Button>
            </div>
          </div>
        </div>
      </ControlPlaneShell>
    );
  }

  const navItems = canUsePlatformAdmin(identity) ? NAV_ITEMS : ORG_NAV_ITEMS;

  return (
    <ControlPlaneShell
      variant="admin"
      topbar={
        <header className="flex h-full w-full items-center justify-between gap-4">
          <p className="text-xs font-medium text-muted-foreground">Organization Admin</p>
          <div className="flex items-center gap-3">
            <Link
              href="/dashboard"
              className="flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to memory banks
            </Link>
            <span className="rounded-full border px-2 py-0.5 text-[10px] text-muted-foreground">
              {identityLabel}
            </span>
          </div>
        </header>
      }
      sidebar={
        <aside className="flex h-full min-h-0 w-56 flex-col overflow-hidden">
          <div className="flex items-center gap-3 border-b border-[var(--shell-border)] px-3.5 py-3">
            <div className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-md bg-primary">
              <ShieldCheck className="h-3.5 w-3.5 text-primary-foreground" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold leading-none">Atulya Admin</p>
              <p className="mt-0.5 text-[10px] text-muted-foreground">Control Plane</p>
            </div>
          </div>
          <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2.5 pb-2.5 pt-3">
            <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Navigate
            </p>
            {navItems.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </Link>
            ))}
          </nav>
          <div className="border-t border-[var(--shell-border)] px-3.5 py-2.5">
            <p className="text-[10px] text-muted-foreground">read/write</p>
          </div>
        </aside>
      }
      contentClassName="max-w-[1400px]"
    >
      {children}
    </ControlPlaneShell>
  );
}
