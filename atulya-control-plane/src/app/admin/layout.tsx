/**
 * Admin section layout — server component.
 *
 * Guards access: if ATULYA_CP_ADMIN_API_KEY is not set → 404 (not 403,
 * to avoid route enumeration). Admin key is NEVER forwarded to the client.
 */

import { notFound } from "next/navigation";
import Link from "next/link";
import {
  Activity,
  ArrowLeft,
  Building2,
  Cpu,
  KeyRound,
  ListOrdered,
  ShieldCheck,
} from "lucide-react";
import { isAdminConfigured } from "@/lib/admin-api";

export const metadata = { title: "Atulya Admin" };

const NAV_ITEMS = [
  { href: "/admin",            label: "System",     icon: Activity },
  { href: "/admin/tenants",    label: "Tenants",    icon: Building2 },
  { href: "/admin/workers",    label: "Workers",    icon: Cpu },
  { href: "/admin/operations", label: "Operations", icon: ListOrdered },
  { href: "/admin/api-keys",   label: "API Keys",   icon: KeyRound },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  if (!isAdminConfigured()) notFound();

  return (
    /*
     * CSS Grid: 2 cols × 2 rows
     *   col 1 = sidebar (14rem fixed)
     *   col 2 = content (1fr)
     *   row 1 = header strip (3.5rem fixed, shared border-bottom)
     *   row 2 = body (fills remaining viewport height)
     */
    <div className="grid min-h-screen grid-cols-[14rem_1fr] grid-rows-[3.5rem_1fr] bg-background">

      {/* ── [row1, col1] Sidebar brand ────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 border-r border-b">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary shrink-0">
          <ShieldCheck className="h-3.5 w-3.5 text-primary-foreground" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold leading-none">Atulya Admin</p>
          <p className="text-[10px] text-muted-foreground mt-0.5">Control Plane</p>
        </div>
      </div>

      {/* ── [row1, col2] Top bar ──────────────────────────────────── */}
      <header className="flex items-center justify-between px-8 border-b bg-muted/10">
        <p className="text-xs text-muted-foreground font-mono">/v1/admin</p>
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard"
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors border rounded-md px-2.5 py-1 hover:bg-accent"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Dashboard
          </Link>
          <span className="text-[10px] text-muted-foreground border rounded-full px-2 py-0.5">
            superuser
          </span>
        </div>
      </header>

      {/* ── [row2, col1] Sidebar nav ──────────────────────────────── */}
      <aside className="flex flex-col border-r overflow-y-auto">
        <nav className="flex-1 px-3 pt-4 pb-3 space-y-0.5">
          <p className="px-2 mb-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Navigate
          </p>
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </Link>
          ))}
        </nav>
        <div className="px-4 py-3 border-t">
          <p className="text-[10px] text-muted-foreground">read/write</p>
        </div>
      </aside>

      {/* ── [row2, col2] Main content ─────────────────────────────── */}
      <main className="overflow-auto">
        <div className="px-8 py-8 w-full max-w-[1400px]">
          {children}
        </div>
      </main>

    </div>
  );
}
