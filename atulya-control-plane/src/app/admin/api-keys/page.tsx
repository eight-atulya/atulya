import { redirect } from "next/navigation";

export default function LegacyAccessPage() {
  redirect("/admin/access");
}
