"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Building2,
  Cpu,
  Database,
  FileClock,
  KeyRound,
  LayoutDashboard,
  ListOrdered,
  Menu,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

const ICONS = {
  overview: LayoutDashboard,
  members: Users,
  keys: KeyRound,
  roles: ShieldCheck,
  access: SlidersHorizontal,
  audit: FileClock,
  health: Activity,
  organizations: Building2,
  workers: Cpu,
  operations: ListOrdered,
  banks: Database,
} satisfies Record<string, LucideIcon>;

export type AdminNavIcon = keyof typeof ICONS;

export function AdminNav({
  items,
  closeOnNavigate = false,
}: {
  items: ReadonlyArray<{ href: string; label: string; icon: AdminNavIcon }>;
  closeOnNavigate?: boolean;
}) {
  const pathname = usePathname();
  return (
    <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2.5 py-3">
      {items.map(({ href, label, icon }) => {
        const Icon = ICONS[icon];
        const active = pathname === href || (href !== "/admin" && pathname.startsWith(`${href}/`));
        const link = (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex h-9 items-center gap-2.5 rounded-md border border-transparent px-2.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-highlight",
              active
                ? "border-highlight bg-highlight/5 font-medium text-highlight"
                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </Link>
        );
        return closeOnNavigate ? (
          <SheetClose asChild key={href}>
            {link}
          </SheetClose>
        ) : (
          link
        );
      })}
    </nav>
  );
}

export function AdminMobileNav({
  orgName,
  orgItems,
  platformItems,
}: {
  orgName: string;
  orgItems: ReadonlyArray<{ href: string; label: string; icon: AdminNavIcon }>;
  platformItems: ReadonlyArray<{ href: string; label: string; icon: AdminNavIcon }>;
}) {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          className="h-8 w-8 md:hidden"
          aria-label="Open navigation"
        >
          <Menu className="h-4 w-4" />
        </Button>
      </SheetTrigger>
      <SheetContent side="left" className="flex w-72 flex-col gap-0 border-highlight p-0">
        <div className="border-b border-highlight/30 px-5 py-4">
          <SheetTitle>Administration</SheetTitle>
          <SheetDescription>{orgName}</SheetDescription>
        </div>
        {orgItems.length > 0 && (
          <div className="flex min-h-0 flex-col">
            <p className="px-5 pb-1 pt-4 text-[10px] font-semibold uppercase text-muted-foreground">
              Workspace
            </p>
            <AdminNav items={orgItems} closeOnNavigate />
          </div>
        )}
        {platformItems.length > 0 && (
          <div className="flex min-h-0 flex-col border-t border-highlight/30">
            <p className="px-5 pb-1 pt-4 text-[10px] font-semibold uppercase text-muted-foreground">
              Platform
            </p>
            <AdminNav items={platformItems} closeOnNavigate />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
