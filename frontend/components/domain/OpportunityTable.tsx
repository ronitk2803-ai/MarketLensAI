import Link from "next/link";

import { Delta } from "@/components/terminal/Delta";
import { compact, num, price, scoreBarTone, scoreTone } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { OpportunityHit } from "@/lib/api";

/** Shared by the preset screener (/opportunities) and the condition
 * builder (/opportunities/advanced) so the two can't drift into rendering
 * the same rows differently. */

const METRIC_LABELS: Record<string, string> = {
  change_pct: "Change",
  pct_below: "Below avg",
  relative_volume: "Rel volume",
  close: "Close",
  dma: "Average",
  volume: "Volume",
  // Condition-tree metrics. Without an entry here a key falls through to
  // its raw name AND to an unlabelled number — which is exactly the
  // units trap the registry's `unit` metadata exists to defuse
  // (debt_to_equity is a percentage, the growth/margin ratios are
  // fractions).
  delivery_pct: "Delivery",
  drawdown_pct: "Drawdown",
  volatility20: "Volatility",
  rsi14: "RSI (14)",
  dma20_gap_pct: "vs 20DMA",
  dma50_gap_pct: "vs 50DMA",
  dma100_gap_pct: "vs 100DMA",
  dma200_gap_pct: "vs 200DMA",
  change_5d_pct: "5d",
  change_10d_pct: "10d",
  change_15d_pct: "15d",
  change_30d_pct: "30d",
  change_60d_pct: "60d",
  change_90d_pct: "90d",
  price_to_book: "P/B",
  trailing_pe: "P/E",
  forward_pe: "Fwd P/E",
  debt_to_equity: "D/E",
  gross_margins: "Gross margin",
  operating_margins: "Op margin",
  profit_margins: "Net margin",
  revenue_growth: "Revenue growth",
  earnings_growth: "Earnings growth",
  return_on_equity: "ROE",
  return_on_assets: "ROA",
  beta: "Beta",
};

// Screens expose different metric sets; this fixes the column order where
// they overlap so the eye doesn't have to re-learn the table per screen.
const METRIC_ORDER = ["close", "change_pct", "pct_below", "dma", "relative_volume", "volume"];

// Keys whose stored value is a fraction (0.15) but reads as a percentage.
const FRACTION_KEYS = new Set([
  "gross_margins",
  "operating_margins",
  "profit_margins",
  "revenue_growth",
  "earnings_growth",
  "return_on_equity",
  "return_on_assets",
  "volatility20",
]);

// Keys already stored as a percentage — shown with a % so they can't be
// mistaken for a ratio (debt_to_equity of 23.8 means 0.24x, not 23.8x).
const PERCENT_KEYS = new Set([
  "debt_to_equity",
  "delivery_pct",
  "drawdown_pct",
  "dma20_gap_pct",
  "dma50_gap_pct",
  "dma100_gap_pct",
  "dma200_gap_pct",
]);

const SIGNED_PERCENT_KEYS = new Set([
  "change_5d_pct",
  "change_10d_pct",
  "change_15d_pct",
  "change_30d_pct",
  "change_60d_pct",
  "change_90d_pct",
]);

function MetricCell({ metricKey, value }: { metricKey: string; value: number | undefined }) {
  if (typeof value !== "number") return <span className="num text-muted-foreground">—</span>;
  if (metricKey === "change_pct" || metricKey === "pct_below") {
    return <Delta value={metricKey === "pct_below" ? -value : value} digits={1} />;
  }
  if (SIGNED_PERCENT_KEYS.has(metricKey)) return <Delta value={value} digits={1} />;
  if (metricKey === "relative_volume") return <span className="num">{num(value, 1)}x</span>;
  if (metricKey === "close" || metricKey === "dma") {
    return <span className="num">{price(value)}</span>;
  }
  if (metricKey === "volume") return <span className="num">{compact(value)}</span>;
  if (FRACTION_KEYS.has(metricKey)) {
    return <span className="num">{(value * 100).toFixed(1)}%</span>;
  }
  if (PERCENT_KEYS.has(metricKey)) return <span className="num">{value.toFixed(1)}%</span>;
  return <span className="num">{num(value)}</span>;
}

export function metricColumnsFor(hits: OpportunityHit[]): string[] {
  // Union across all hits, not just hits[0] — a screen whose first row
  // happens to omit a metric would otherwise drop that column for every row.
  const presentKeys = new Set<string>();
  for (const hit of hits) {
    for (const key of Object.keys(hit.metrics)) {
      if (key !== "period_days") presentKeys.add(key);
    }
  }
  return [
    ...METRIC_ORDER.filter((k) => presentKeys.has(k)),
    ...[...presentKeys].filter((k) => !METRIC_ORDER.includes(k)).sort(),
  ];
}

export function OpportunityTable({ hits }: { hits: OpportunityHit[] }) {
  const metricKeys = metricColumnsFor(hits);

  return (
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
  );
}
