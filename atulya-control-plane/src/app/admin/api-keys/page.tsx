/**
 * Admin › Access Control
 *
 * Org-aware users, service keys, action grants, roles, and audit events.
 */

import { AdminAccessConsole } from "@/components/admin-access-console";
import { adminFetch, OrgResponse } from "@/lib/admin-api";
import { getCurrentIdentity } from "@/lib/server-auth";

export default async function AdminApiKeysPage() {
  let orgs: OrgResponse[] = [];
  let error: string | null = null;

  try {
    const identity = await getCurrentIdentity();
    orgs = await adminFetch<OrgResponse[]>("/orgs");
    if (identity && !identity.is_superuser) {
      orgs = orgs.filter((org) => org.id === identity.org_id);
    }
  } catch (e) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
        {error}
      </div>
    );
  }

  return <AdminAccessConsole initialOrgs={orgs} />;
}
