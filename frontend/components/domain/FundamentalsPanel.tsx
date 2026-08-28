import { KpiLabel } from "@/components/domain/KpiLabel";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import { crores, croreShares, DASH } from "@/lib/format";
import { marketCapCategory, marketCapCategoryTone } from "@/lib/market-cap";
import { cn } from "@/lib/utils";
import type { Fundamentals, Meta, SectorPe } from "@/lib/api";

const RATIO_LABELS: Record<string, string> = {
  debtToEquity: "Debt / Equity",
  grossMargins: "Gross margin",
  operatingMargins: "Operating margin",
  profitMargins: "Net margin",
  revenueGrowth: "Revenue growth",
  earningsGrowth: "Earnings growth",
  returnOnEquity: "ROE",
  returnOnAssets: "ROA",
  priceToBook: "P / B",
  forwardPE: "Forward P/E",
  trailingPE: "P/E (TTM)",
  beta: "Beta",
  marketCap: "Market cap",
  sharesOutstanding: "Shares outstanding",
  floatShares: "Free float",
};

const PERCENT_METRICS = new Set([
  "grossMargins",
  "operatingMargins",
  "profitMargins",
  "revenueGrowth",
  "earningsGrowth",
  "returnOnEquity",
  "returnOnAssets",
]);

// These three ride in on the same ratios array as P/E, ROE etc. (same
// provider payload, same cache) but read as rupee/share-count figures, not
// small decimals or percentages, so they need their own formatting branch
// rather than falling into formatRatio's percent-or-two-decimals default.
const RUPEE_SCALE_METRICS = new Set(["marketCap"]);
const SHARE_COUNT_METRICS = new Set(["sharesOutstanding", "floatShares"]);

const LINE_ITEM_LABELS: Record<string, string> = {
  totalRevenue: "Revenue",
  netIncome: "Net income",
  grossProfit: "Gross profit",
  operatingIncome: "Operating income",
  ebit: "EBIT",
};

function formatRatio(metric: string, value: number): string {
  if (RUPEE_SCALE_METRICS.has(metric)) return crores(value);
  if (SHARE_COUNT_METRICS.has(metric)) return croreShares(value);
  if (PERCENT_METRICS.has(metric)) return `${(value * 100).toFixed(1)}%`;
  return value.toFixed(2);
}

/**
 * "Is this P/E high or low" is a question this company's own numbers can't
 * answer alone — this is what actually answers it, next to the figure
 * that prompted it rather than in a separate panel the reader has to go
 * find.
 *
 * Trailing P/E prefers NSE's own sectoral-index figure (the real, official
 * "what's this sector trading at," computed by NSE across the index's
 * full constituent set — see app/services/sector_index.py) and labels it
 * as such; only when this company's industry has no matching Nifty
 * sectoral index does it fall back to a median across whichever
 * same-industry companies this app has fundamentals cached for, and that
 * fallback is also labelled so the two are never confused for each other.
 * Forward P/E has no NSE equivalent, so it's always the peer median.
 *
 * `null` throughout (never "0 companies") whenever there's nothing
 * meaningful to show — a thin data day reads as "not enough data yet,"
 * never as a two-company average dressed up as a sector figure.
 */
function sectorPeLine(metric: string, sectorPe: SectorPe): string | null {
  if (metric === "trailingPE" && sectorPe.trailing_pe != null) {
    const value = sectorPe.trailing_pe.toFixed(2);
    if (sectorPe.trailing_pe_source === "nse_index") {
      return `${sectorPe.trailing_pe_index_name} ${value}`;
    }
    return `Sector median ${value} (n=${sectorPe.trailing_pe_sample_size})`;
  }
  if (metric === "forwardPE" && sectorPe.forward_median != null) {
    return `Sector median ${sectorPe.forward_median.toFixed(2)} (n=${sectorPe.forward_sample_size})`;
  }
  return null;
}

export function FundamentalsPanel({
  fundamentals,
  meta,
  industry,
}: {
  fundamentals: Fundamentals;
  meta: Meta;
  /** Also shown in the page header — repeated here so it reads next to
      market cap / cap size rather than requiring a scroll back up. */
  industry?: string | null;
}) {
  const hasData = fundamentals.ratios.length > 0 || fundamentals.income_statement.length > 0;

  // Coverage is uneven period-by-period (Yahoo's Indian-ticker data is
  // "spotty and inconsistent" per Build_plan.md §H) — don't assume every
  // period has the same line items. Use the union of keys across periods
  // for the header and show "—" per-cell for what a period is missing,
  // rather than silently misaligning columns.
  const lineItemKeys = Array.from(
    new Set(fundamentals.income_statement.flatMap((p) => Object.keys(p.line_items))),
  );

  // Derived client-side from marketCap rather than sent by the backend: a
  // pure function of a number already on the page, so there is no reason
  // to round-trip it through an API for a purely presentational badge.
  const marketCap = fundamentals.ratios.find((r) => r.metric === "marketCap")?.value ?? null;
  const capCategory = marketCapCategory(marketCap);

  return (
    <Panel
      title="Fundamentals"
      actions={<ProvenanceBadge source={meta.source} asOf={meta.as_of} confidence={meta.confidence} />}
      bodyClassName="p-0"
      footnote="Best-effort, single-source data — always shown at low confidence. Missing fields are omitted, never estimated. Provided for research purposes only, not investment advice."
      fullscreenable
    >
      {!hasData ? (
        <p className="px-3 py-8 text-center text-xs text-muted-foreground">
          No fundamentals available for this company yet.
        </p>
      ) : (
        <div className="flex flex-col">
          {fundamentals.ratios.length > 0 && (
            <div className="grid grid-cols-2 gap-y-3 p-3 sm:grid-cols-4 lg:grid-cols-6">
              {industry && (
                <div className="flex flex-col gap-0.5 border-l border-border px-3 first:border-l-0 first:pl-0">
                  <span className="label-caps">Industry</span>
                  <span className="truncate text-sm font-medium" title={industry}>
                    {industry}
                  </span>
                </div>
              )}
              {capCategory && (
                <div className="flex flex-col gap-0.5 border-l border-border px-3 first:border-l-0 first:pl-0">
                  <KpiLabel metric="marketCapCategory" label="Cap size" />
                  <span className={cn("num text-sm font-medium", marketCapCategoryTone(capCategory))}>
                    {capCategory}
                  </span>
                </div>
              )}
              {fundamentals.ratios.map((r) => {
                const sectorLine = sectorPeLine(r.metric, fundamentals.sector_pe);
                return (
                  <div
                    key={r.metric}
                    className="flex flex-col gap-0.5 border-l border-border px-3 first:border-l-0 first:pl-0"
                  >
                    <KpiLabel metric={r.metric} label={RATIO_LABELS[r.metric] ?? r.metric} />
                    <span className="num text-sm font-medium">
                      {formatRatio(r.metric, r.value)}
                    </span>
                    {sectorLine && (
                      <span className="num text-[10.5px] text-muted-foreground">{sectorLine}</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {fundamentals.income_statement.length > 0 && (
            <div className="overflow-x-auto border-t border-border">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="border-b border-border bg-surface-raised/40">
                    <th className="label-caps px-3 py-1.5 text-left">Fiscal year</th>
                    {lineItemKeys.map((key) => (
                      <th key={key} className="label-caps py-1.5 pr-3 text-right whitespace-nowrap">
                        {LINE_ITEM_LABELS[key] ?? key}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {fundamentals.income_statement.map((period) => (
                    <tr key={period.period_end} className="border-b border-border/50 last:border-0">
                      <td className="num px-3 py-1.5">{period.period_end}</td>
                      {lineItemKeys.map((key) => (
                        <td key={key} className="num py-1.5 pr-3 text-right whitespace-nowrap">
                          {key in period.line_items ? crores(period.line_items[key]) : DASH}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
