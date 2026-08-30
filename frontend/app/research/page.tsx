import Link from "next/link";

import { ResearchAssistantPanel } from "@/components/domain/ResearchAssistantPanel";
import { Panel } from "@/components/terminal/Panel";
import { getSignedInSession } from "@/lib/session";

// Auth-gated (matches the backend's get_current_verified_user) and never
// worth freezing into the build — same reasoning as /portfolio.
export const dynamic = "force-dynamic";

export default async function ResearchPage() {
  const session = await getSignedInSession();

  if (!session) {
    return (
      <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-3 px-4 py-4">
        <Panel title="Research assistant" bodyClassName="p-0">
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            <Link href="/login" className="text-primary hover:underline">
              Sign in
            </Link>{" "}
            to ask the research assistant a question.
          </p>
        </Panel>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-3 px-4 py-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Research assistant</h1>
        <p className="text-xs text-muted-foreground">
          Ask a question in plain language — every answer is grounded in this app&rsquo;s own
          stored data, never a general-knowledge guess.
        </p>
      </div>
      <ResearchAssistantPanel />
    </main>
  );
}
