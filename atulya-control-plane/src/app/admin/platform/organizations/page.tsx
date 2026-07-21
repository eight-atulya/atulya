import { PlatformOrganizationsPage } from "@/components/platform-organizations-page";
import { PlatformAdminRequired } from "@/components/platform-admin-required";
import { canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

export default async function OrganizationsPage() {
  const identity = await getCurrentIdentity();
  if (!canUsePlatformAdmin(identity)) return <PlatformAdminRequired />;
  return <PlatformOrganizationsPage />;
}
