import Link from "next/link";

import { Panel } from "@/components/terminal/Panel";
import { cn } from "@/lib/utils";
import { getTheses } from "@/lib/api";
import { getSignedInSession } from "@/lib/session";
import type { ThesisStance, ThesisStatus, ThesisSummary } from "@/lib/api";

export const dynamic = "force-dynamic";

const STANCE_TONE: Record<ThesisStance, string> = {
  bull: "text-up",
  bear: "text-down",
  neutral: "text-muted-foreground",
};

const STATUS_TONE: Record<ThesisStatus, string> = {
  active: "text-muted-foreground",
  challenged: "text-[color:var(--chart-2)]",
  invalidated: "text-down",
  closed: "text-muted-foreground",
};

function ThesisRow({ thesis }: { thesis: ThesisSummary }) {
  return (
    <li className="border-b border-border/60 last:border-0">
      <Link
        href={`/theses/${thesis.id}`}
        className="flex items-center justify-between gap-3 px-3 py-2.5 hover:bg-accent/40"
      >
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">{thesis.title}</span>
          <span className="num text-[11px] text-muted-foreground">
            {thesis.symbol} · {thesis.asset_name}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-3 text-[11px]">
          <span className={cn("font-medium", STANCE_TONE[thesis.stance])}>
            {thesis.stance}
          </span>
          <span className={cn(STATUS_TONE[thesis.status])}>{thesis.status}</span>
        </span>
      </Link>
    </li>
  );
}

export default async function ThesesPage() {
  const session = await getSignedInSession();

  if (!session) {
    return (
      <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-3 px-4 py-4">
        <Panel title="Theses" bodyClassName="p-0">
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            <Link href="/login" className="text-primary hover:underline">
              Sign in
            </Link>{" "}
            to track a thesis.
          </p>
        </Panel>
      </main>
    );
  }

  const theses = await getTheses(session.accessToken).catch(() => []);

  return (
    <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-3 px-4 py-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Theses</h1>
          <p className="text-xs text-muted-foreground">
            What you believe about a stock, and what would prove it wrong.
          </p>
        </div>
        <Link
          href="/theses/new"
          className="rounded-sm bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/80"
        >
          New thesis
        </Link>
      </div>

      <Panel bodyClassName="p-0">
        {theses.length === 0 ? (
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            No theses yet — record what you believe and what would change your mind.
          </p>
        ) : (
          <ul>
            {theses.map((thesis) => (
              <ThesisRow key={thesis.id} thesis={thesis} />
            ))}
          </ul>
        )}
      </Panel>
    </main>
  );
}
