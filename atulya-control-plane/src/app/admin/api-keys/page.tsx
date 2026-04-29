/**
 * Admin › API Keys
 *
 * Lists all API keys (redacted — raw key shown once at creation only).
 * Create/revoke via the admin REST API.
 *
 */

import { Ban, CheckCircle2, KeyRound, ShieldCheck, User, XCircle } from "lucide-react";
import { adminFetch, ApiKeyResponse } from "@/lib/admin-api";

const ROLE_CONFIG: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  superuser: {
    label: "Superuser",
    color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    icon: ShieldCheck,
  },
  admin: {
    label: "Admin",
    color: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
    icon: ShieldCheck,
  },
  user: {
    label: "User",
    color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
    icon: User,
  },
};

export default async function AdminApiKeysPage() {
  let keys: ApiKeyResponse[] = [];
  let error: string | null = null;

  try {
    keys = await adminFetch<ApiKeyResponse[]>("/api-keys");
  } catch (e) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  const active = keys.filter((k) => !k.revoked_at);
  const revoked = keys.filter((k) => k.revoked_at);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">API Keys</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {active.length} active · {revoked.length} revoked
          </p>
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
          <KeyRound className="h-4 w-4 text-muted-foreground" />
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive flex items-center gap-2">
          <XCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Security notice */}
      <div className="rounded-lg border bg-muted/30 px-4 py-3 flex items-start gap-3">
        <ShieldCheck className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
        <div>
          <p className="text-xs font-medium">Raw keys are never displayed after creation</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            To create: <code className="bg-muted px-1 rounded">POST /v1/admin/api-keys</code> · To
            revoke:{" "}
            <code className="bg-muted px-1 rounded ml-1">DELETE /v1/admin/api-keys/:id</code>
          </p>
        </div>
      </div>

      {/* Active keys */}
      {active.length > 0 && (
        <div className="rounded-lg border bg-card shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30 flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Active Keys
            </p>
            <div className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
              <CheckCircle2 className="h-3 w-3" />
              {active.length}
            </div>
          </div>
          <div className="divide-y">
            {active.map((k) => {
              const role = ROLE_CONFIG[k.role] ?? ROLE_CONFIG.user;
              const RoleIcon = role.icon;
              return (
                <div
                  key={k.id}
                  className="flex items-center gap-4 px-4 py-3 hover:bg-muted/20 transition-colors"
                >
                  <div
                    className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold shrink-0 ${role.color}`}
                  >
                    <RoleIcon className="h-2.5 w-2.5" />
                    {role.label}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">
                      {k.name ?? <span className="text-muted-foreground italic">unnamed</span>}
                    </p>
                    <p className="text-xs text-muted-foreground font-mono">
                      {k.id.slice(0, 16)}… · schema: {k.schema_name}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    {k.expires_at ? (
                      <p className="text-xs text-muted-foreground">
                        expires <span className="font-mono">{k.expires_at.slice(0, 10)}</span>
                      </p>
                    ) : (
                      <p className="text-xs text-muted-foreground">no expiry</p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      created {k.created_at?.slice(0, 10)}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Revoked keys */}
      {revoked.length > 0 && (
        <div className="rounded-lg border bg-card shadow-sm overflow-hidden opacity-60">
          <div className="px-4 py-3 border-b bg-muted/30 flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Revoked Keys
            </p>
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Ban className="h-3 w-3" />
              {revoked.length}
            </div>
          </div>
          <div className="divide-y">
            {revoked.map((k) => (
              <div key={k.id} className="flex items-center gap-4 px-4 py-2.5">
                <Ban className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                <p className="text-xs font-mono text-muted-foreground line-through flex-1">
                  {k.name ?? k.id.slice(0, 16)}
                </p>
                <p className="text-xs text-muted-foreground shrink-0">
                  revoked {k.revoked_at?.slice(0, 10)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {keys.length === 0 && !error && (
        <div className="rounded-lg border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
          No API keys found. Create one with{" "}
          <code className="bg-muted px-1 rounded">POST /v1/admin/api-keys</code>.
        </div>
      )}
    </div>
  );
}
