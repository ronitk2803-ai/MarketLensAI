import Link from "next/link";

import { MarkAlertsRead } from "@/components/domain/MarkAlertsRead";
import { Panel } from "@/components/terminal/Panel";
import { cn } from "@/lib/utils";
import { getAlerts } from "@/lib/api";
import { getSignedInSession } from "@/lib/session";
import { relativeTime, tradingDate } from "@/lib/format";
import type { AlertKind, UserAlert } from "@/lib/api";

export const dynamic = "force-dynamic";

const KIND_LABELS: Record<AlertKind, string> = {
  thesis_challenged: "Thesis challenged",
  price_drop: "Price drop",
  price_surge: "Price surge",
  unusual_volume: "Unusual volume",
  week52_high: "52-week high",
  week52_low: "52-week low",
};

// A thesis being challenged is the user's own stated condition firing —
// the one kind that carries a judgement rather than an observation.
const KIND_TONE: Record<AlertKind, string> = {
  thesis_challenged: "bg-[color:var(--chart-2)]/15 text-[color:var(--chart-2)]",
  price_drop: "bg-down/10 text-down",
  price_surge: "bg-up/10 text-up",
  unusual_volume: "bg-primary/10 text-primary",
  week52_high: "bg-up/10 text-up",
  week52_low: "bg-down/10 text-down",
};

function AlertRow({ alert }: { alert: UserAlert }) {
  const unread = alert.read_at === null;
  return (
    <li
      className={cn(
        "flex flex-col gap-1 border-b border-border/60 px-3 py-2.5 last:border-0",
        unread && "bg-accent/30",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        {unread && (
          <span className="size-1.5 shrink-0 rounded-full bg-primary" aria-label="Unread" />
        )}
        <span
          className={cn("rounded-sm px-1.5 py-0.5 text-[10px] uppercase", KIND_TONE[alert.kind])}
        >
          {KIND_LABELS[alert.kind] ?? alert.kind}
        </span>
        <Link
          href={`/company/${alert.symbol}`}
          className="num text-sm font-medium hover:text-primary hover:underline"
        >
          {alert.symbol}
        </Link>
        <span className="ml-auto text-[11px] text-muted-foreground">
          {relativeTime(alert.created_at)}
        </span>
      </div>
      <p className="text-sm">{alert.title}</p>
      {alert.body && <p className="text-xs text-muted-foreground">{alert.body}</p>}
      {/* End-of-day figures surfaced hours after the close, so the bar date
          they came from is part of the claim, not decoration. */}
      <p className="text-[11px] text-muted-foreground">
        Session of {tradingDate(alert.as_of)}
      </p>
    </li>
  );
}

export default async function AlertsPage() {
  const session = await getSignedInSession();

  if (!session) {
    return (
      <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-3 px-4 py-4">
        <Panel title="Alerts" bodyClassName="p-0">
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            <Link href="/login" className="text-primary hover:underline">
              Sign in
            </Link>{" "}
            to see your alerts.
          </p>
        </Panel>
      </main>
    );
  }

  const result = await getAlerts(session.accessToken, { limit: 100 }).catch(() => ({
    alerts: [],
    unread_count: 0,
  }));

  return (
    <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-3 px-4 py-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Alerts</h1>
          <p className="text-xs text-muted-foreground">
            Triggers you set that fired, and notable moves on stocks you watch.
          </p>
        </div>
        <MarkAlertsRead unreadCount={result.unread_count} />
      </div>

      <Panel bodyClassName="p-0">
        {result.alerts.length === 0 ? (
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            Nothing yet. Alerts are generated once a day after the market close — from thesis
            triggers you&apos;ve set and from notable moves on your watchlist.
          </p>
        ) : (
          <ul>
            {result.alerts.map((alert) => (
              <AlertRow key={alert.id} alert={alert} />
            ))}
          </ul>
        )}
      </Panel>
    </main>
  );
}
