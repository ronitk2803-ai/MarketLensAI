import Link from "next/link";

import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Delta } from "@/components/terminal/Delta";
import { Panel } from "@/components/terminal/Panel";
import { getOpportunities, getOpportunityScreens } from "@/lib/api";
import { compact, num, price, scoreBarTone, scoreTone } from "@/lib/format";
import { cn } from "@/lib/utils";

// This is a static route (no [param] segment), so Next attempts to
// prerender it at build time by default — which fails when the backend
// isn't running during `next build` (verified live: ECONNREFUSED against
// API_BASE_URL). Screening results should reflect current data on each
// request anyway (the fetch-level `revalidate` above already bounds
// staleness), so force this dynamic rather than statically cached.
export const dynamic = "force-dynamic";

const METRIC_LABELS: Record<string, string> = {
  change_pct: "Change",
  pct_below: "Below avg",
  relative_volume: "Rel volume",
  close: "Close",
  dma: "Average",
  volume: "Volume",
};

// Screens expose different metric sets; this fixes the column order where
// they overlap so the eye doesn't have to re-learn the table per screen.
const METRIC_ORDER = ["close", "change_pct", "pct_below", "dma", "relative_volume", "volume"];

function MetricCell({ metricKey, value }: { metricKey: string; value: number | undefined }) {
  if (typeof value !== "number") return <span className="num text-muted-foreground">—</span>;
  if (metricKey === "change_pct" || metricKey === "pct_below") {
    return <Delta value={metricKey === "pct_below" ? -value : value} digits={1} />;
  }
  if (metricKey === "relative_volume") return <span className="num">{num(value, 1)}x</span>;
  if (metricKey === "close" || metricKey === "dma") return <span className="num">{price(value)}</span>;
  if (metricKey === "volume") return <span className="num">{compact(value)}</span>;
  return <span className="num">{num(value)}</span>;
}

export default async function OpportunitiesPage({
  searchParams,
}: {
  searchParams: Promise<{ screen?: string }>;
}) {
  const screensResult = await getOpportunityScreens();
  const screens = screensResult.data;
  const { screen: rawScreen } = await searchParams;
  const activeScreen =
    rawScreen && screens.some((s) => s.id === rawScreen) ? rawScreen : (screens[0]?.id ?? "");

  const result = activeScreen ? await getOpportunities(activeScreen) : null;
  const hits = result?.data ?? [];

  // Union across all hits, not just hits[0] — a screen whose first row
  // happens to omit a metric would otherwise drop that column for every row.
  const presentKeys = new Set<string>();
  for (const hit of hits) {
    for (const key of Object.keys(hit.metrics)) {
      if (key !== "period_days") presentKeys.add(key);
    }
  }
  const metricKeys = [
    ...METRIC_ORDER.filter((k) => presentKeys.has(k)),
    ...[...presentKeys].filter((k) => !METRIC_ORDER.includes(k)).sort(),
  ];

  const scored = hits.filter((h) => typeof h.opportunity_score === "number");

  return (
    <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-3 px-4 py-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Screener</h1>
        <p className="text-xs text-muted-foreground">
          What deserves attention right now — screened against stored end-of-day data. Research
          candidates, not recommendations.
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {screens.map((s) => (
          <Link
            key={s.id}
            href={`/opportunities?screen=${s.id}`}
            className={cn(
              "rounded-sm border px-2.5 py-1 text-xs transition-colors",
              s.id === activeScreen
                ? "border-primary bg-primary/15 font-medium text-foreground"
                : "border-border text-muted-foreground hover:bg-accent/60 hover:text-foreground",
            )}
          >
            {s.label}
          </Link>
        ))}
      </div>

      <Panel
        title={
          <div className="flex items-baseline gap-3">
            <h2 className="label-caps">
              {screens.find((s) => s.id === activeScreen)?.label ?? "Results"}
            </h2>
            <span className="num text-[11px] text-muted-foreground">
              {hits.length} match{hits.length === 1 ? "" : "es"}
              {scored.length !== hits.length && ` · ${scored.length} scored`}
            </span>
          </div>
        }
        actions={
          result && (
            <ProvenanceBadge
              source={result.meta.source}
              asOf={result.meta.as_of}
              confidence={result.meta.confidence}
            />
          )
        }
        bodyClassName="p-0"
        footnote="Ranked by Opportunity Score where available — attention-worthiness, not raw decline. Rows without a score yet sort after every scored row."
      >
        {hits.length === 0 ? (
          <p className="px-3 py-10 text-center text-sm text-muted-foreground">
            No matches right now — either nothing meets the threshold, or the universe
            doesn&apos;t have enough price history yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-border bg-surface-raised/40">
                  <th className="label-caps px-3 py-1.5 text-right">#</th>
                  <th className="label-caps py-1.5 text-left">Symbol</th>
                  {/* On a phone the name eats the width the numbers need,
                      and the symbol already identifies the row. */}
                  <th className="label-caps hidden py-1.5 text-left sm:table-cell">Company</th>
                  <th className="label-caps py-1.5 pr-3 text-right">Score</th>
                  {metricKeys.map((key) => (
                    <th key={key} className="label-caps py-1.5 pr-3 text-right whitespace-nowrap">
                      {METRIC_LABELS[key] ?? key}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {hits.map((hit) => (
                  <tr
                    key={hit.symbol}
                    className="border-b border-border/50 last:border-0 hover:bg-accent/40"
                  >
                    <td className="num px-3 py-1.5 text-right text-muted-foreground">{hit.rank}</td>
                    <td className="py-1.5">
                      <Link
                        href={`/company/${hit.symbol}`}
                        className="num font-medium hover:text-primary hover:underline"
                      >
                        {hit.symbol}
                      </Link>
                    </td>
                    <td className="hidden max-w-[18rem] truncate py-1.5 pr-3 text-muted-foreground sm:table-cell">
                      {hit.name}
                    </td>
                    <td className="py-1.5 pr-3">
                      {typeof hit.opportunity_score !== "number" ? (
                        <span className="num block text-right text-muted-foreground">—</span>
                      ) : (
                        <div className="flex items-center justify-end gap-2">
                          <div className="h-1 w-10 overflow-hidden rounded-full bg-muted">
                            <div
                              className={cn("h-full", scoreBarTone(hit.opportunity_score))}
                              style={{ width: `${hit.opportunity_score}%` }}
                            />
                          </div>
                          <span
                            className={cn(
                              "num w-6 text-right font-medium",
                              scoreTone(hit.opportunity_score),
                            )}
                          >
                            {hit.opportunity_score.toFixed(0)}
                          </span>
                        </div>
                      )}
                    </td>
                    {metricKeys.map((key) => (
                      <td key={key} className="py-1.5 pr-3 text-right whitespace-nowrap">
                        <MetricCell metricKey={key} value={hit.metrics[key]} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </main>
  );
}
