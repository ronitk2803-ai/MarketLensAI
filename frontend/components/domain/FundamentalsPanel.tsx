import { KpiLabel } from "@/components/domain/KpiLabel";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import { crores, croreShares, DASH } from "@/lib/format";
import { marketCapCategory, marketCapCategoryTone } from "@/lib/market-cap";
import { cn } from "@/lib/utils";
import type { Fundamentals, Meta } from "@/lib/api";

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

export function FundamentalsPanel({
  fundamentals,
  meta,
}: {
  fundamentals: Fundamentals;
  meta: Meta;
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
      footnote="Best-effort, single-source data — always shown at low confidence. Missing fields are omitted, never estimated."
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
              {capCategory && (
                <div className="flex flex-col gap-0.5 border-l border-border px-3 first:border-l-0 first:pl-0">
                  <KpiLabel metric="marketCapCategory" label="Cap size" />
                  <span className={cn("num text-sm font-medium", marketCapCategoryTone(capCategory))}>
                    {capCategory}
                  </span>
                </div>
              )}
              {fundamentals.ratios.map((r) => (
                <div
                  key={r.metric}
                  className="flex flex-col gap-0.5 border-l border-border px-3 first:border-l-0 first:pl-0"
                >
                  <KpiLabel metric={r.metric} label={RATIO_LABELS[r.metric] ?? r.metric} />
                  <span className="num text-sm font-medium">
                    {formatRatio(r.metric, r.value)}
                  </span>
                </div>
              ))}
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
