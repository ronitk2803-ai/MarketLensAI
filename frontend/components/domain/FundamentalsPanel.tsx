import { KpiLabel } from "@/components/domain/KpiLabel";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import { DASH } from "@/lib/format";
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

const LINE_ITEM_LABELS: Record<string, string> = {
  totalRevenue: "Revenue",
  netIncome: "Net income",
  grossProfit: "Gross profit",
  operatingIncome: "Operating income",
  ebit: "EBIT",
};

function formatRatio(metric: string, value: number): string {
  if (PERCENT_METRICS.has(metric)) return `${(value * 100).toFixed(1)}%`;
  return value.toFixed(2);
}

function formatCrores(value: number): string {
  // Values arrive in raw rupees; ₹1 crore = 1e7.
  return `₹${(value / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`;
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
                          {key in period.line_items
                            ? formatCrores(period.line_items[key])
                            : DASH}
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
