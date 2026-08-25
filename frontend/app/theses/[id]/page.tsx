import { notFound, redirect } from "next/navigation";

import { Panel } from "@/components/terminal/Panel";
import { ThesisActions } from "@/components/domain/ThesisActions";
import { ThesisCard } from "@/components/domain/ThesisCard";
import { ApiError, getThesis } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { getSignedInSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function ThesisDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const session = await getSignedInSession();
  if (!session) {
    redirect("/login");
  }

  const thesisId = Number(id);
  if (!Number.isInteger(thesisId)) {
    notFound();
  }

  let thesis;
  try {
    thesis = await getThesis(session.accessToken, thesisId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-3 px-4 py-4">
      <ThesisCard thesis={thesis} />

      <ThesisActions id={thesis.id} status={thesis.status} />

      <Panel
        title="Trigger history"
        footnote="An append-only log — only the moment a trigger first fires is recorded, not every day it stays fired."
        bodyClassName="p-0"
      >
        {thesis.events.length === 0 ? (
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            Nothing has fired yet — this thesis hasn&apos;t been challenged.
          </p>
        ) : (
          <ul>
            {thesis.events.map((event) => (
              <li
                key={event.id}
                className="flex items-baseline justify-between gap-3 border-b border-border/60 px-3 py-2 text-sm last:border-0"
              >
                <span className="num">
                  {event.metric} {event.operator} {event.threshold}
                  {event.observed_value != null && (
                    <span className="text-muted-foreground"> — observed {event.observed_value}</span>
                  )}
                  {event.note && (
                    <span className="block text-[11px] text-muted-foreground">{event.note}</span>
                  )}
                </span>
                <span className="shrink-0 text-[11px] text-muted-foreground">
                  {relativeTime(event.fired_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </main>
  );
}
