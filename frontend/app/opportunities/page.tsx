import Link from "next/link";

import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getOpportunities, getOpportunityScreens } from "@/lib/api";

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
  relative_volume: "vs avg volume",
  close: "Close",
  dma: "Average",
  period_days: "",
  volume: "Volume",
};

function formatMetric(key: string, value: number): string {
  if (key === "change_pct" || key === "pct_below") return `${value.toFixed(1)}%`;
  if (key === "relative_volume") return `${value.toFixed(1)}x`;
  if (key === "close" || key === "dma") return `₹${value.toFixed(2)}`;
  if (key === "volume") return value.toLocaleString("en-IN");
  return value.toFixed(2);
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
  const metricKeys = hits.length > 0 ? Object.keys(hits[0].metrics).filter((k) => k !== "period_days") : [];

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Opportunity Finder</h1>
        <p className="text-sm text-muted-foreground">
          What deserves attention right now — screened against stored data, not a live scan.
          Research candidates, not recommendations.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {screens.map((s) => (
          <Link
            key={s.id}
            href={`/opportunities?screen=${s.id}`}
            className={`rounded-full border px-3 py-1 text-sm ${
              s.id === activeScreen
                ? "border-foreground bg-accent font-medium"
                : "text-muted-foreground hover:bg-accent"
            }`}
          >
            {s.label}
          </Link>
        ))}
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm font-medium">
            {screens.find((s) => s.id === activeScreen)?.label ?? "Results"} · {hits.length} match
            {hits.length === 1 ? "" : "es"}
          </CardTitle>
          {result && (
            <ProvenanceBadge
              source={result.meta.source}
              asOf={result.meta.as_of}
              confidence={result.meta.confidence}
            />
          )}
        </CardHeader>
        <CardContent>
          {hits.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No matches right now — either nothing meets the threshold, or the seeded universe
              doesn&apos;t have enough price history yet.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-1.5 pr-4 font-normal">Symbol</th>
                    <th className="py-1.5 pr-4 font-normal">Name</th>
                    {metricKeys.map((key) => (
                      <th key={key} className="py-1.5 pr-4 font-normal">
                        {METRIC_LABELS[key] ?? key}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {hits.map((hit) => (
                    <tr key={hit.symbol} className="border-b last:border-0">
                      <td className="py-1.5 pr-4">
                        <Link href={`/company/${hit.symbol}`} className="font-medium hover:underline">
                          {hit.symbol}
                        </Link>
                        <Badge variant="outline" className="ml-2">
                          {hit.exchange}
                        </Badge>
                      </td>
                      <td className="py-1.5 pr-4 text-muted-foreground">{hit.name}</td>
                      {metricKeys.map((key) => (
                        <td key={key} className="py-1.5 pr-4 tabular-nums">
                          {formatMetric(key, hit.metrics[key])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
