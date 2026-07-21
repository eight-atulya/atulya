import { Suspense } from "react";
import { AuthCompletionPanel } from "@/components/auth-completion-panel";

export default function InvitePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center px-5">
      <div className="w-full">
        <Suspense>
          <AuthCompletionPanel mode="invite" />
        </Suspense>
      </div>
    </main>
  );
}
