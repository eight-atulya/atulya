import { OrganizationAdminPage } from "@/components/organization-admin-page";
import { redirect } from "next/navigation";
import { canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

export default async function AdminOverviewPage() {
  const identity = await getCurrentIdentity();
  if (!identity?.active_org_id && canUsePlatformAdmin(identity)) redirect("/admin/platform");
  const actions = new Set(identity?.allowed_actions || []);
  if (!actions.has("bank.read")) {
    if (actions.has("admin.users")) redirect("/admin/members");
    if (actions.has("admin.keys")) redirect("/admin/service-accounts");
    if (actions.has("admin.grants")) redirect("/admin/access");
    if (actions.has("admin.audit")) redirect("/admin/audit");
  }
  return <OrganizationAdminPage section="overview" />;
}
