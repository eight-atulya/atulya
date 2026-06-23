import { cn } from "@/lib/utils";

type ControlPlaneShellVariant = "bank" | "landing" | "admin";

interface ControlPlaneShellProps {
  topbar: React.ReactNode;
  sidebar?: React.ReactNode;
  children: React.ReactNode;
  variant: ControlPlaneShellVariant;
  contentClassName?: string;
}

const contentDefaults: Record<ControlPlaneShellVariant, string> = {
  bank: "p-5 sm:p-6",
  landing: "px-4 py-8 sm:px-6 sm:py-10",
  admin: "p-5 sm:p-8",
};

/*
 * Future-agent contract:
 * - This shell owns viewport geometry, outer gaps, floating surfaces, and scroll boundaries.
 * - Topbar/sidebar children are content only; they must not draw their own shell panels.
 * - Main is the only page scroll region; pages should not create viewport shells or offset chrome.
 * - Route pages own product content and business logic only.
 */
export function ControlPlaneShell({
  topbar,
  sidebar,
  children,
  variant,
  contentClassName,
}: ControlPlaneShellProps) {
  return (
    <div
      data-shell-variant={variant}
      data-has-sidebar={sidebar ? "true" : "false"}
      className="control-plane-shell text-foreground"
    >
      <div className="control-plane-topbar control-plane-surface">{topbar}</div>
      {sidebar ? (
        <div className="control-plane-sidebar-slot control-plane-surface">{sidebar}</div>
      ) : null}
      <main className="control-plane-main">
        <div
          className={cn("mx-auto min-h-full w-full", contentDefaults[variant], contentClassName)}
        >
          {children}
        </div>
      </main>
    </div>
  );
}
