import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import type { Fundamentals, Meta } from "@/lib/api";

const RATIO_LABELS: Record<string, string> = {
  debtToEquity: "Debt / Equity",
  grossMargins: "Gross Margin",
  operatingMargins: "Operating Margin",
  profitMargins: "Net Margin",
  revenueGrowth: "Revenue Growth",
  earningsGrowth: "Earnings Growth",
  returnOnEquity: "ROE",
  returnOnAssets: "ROA",
  priceToBook: "P/B",
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
  netIncome: "Net Income",
  grossProfit: "Gross Profit",
  operatingIncome: "Operating Income",
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

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-sm font-medium">Fundamentals</CardTitle>
        <ProvenanceBadge source={meta.source} asOf={meta.as_of} confidence={meta.confidence} />
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {!hasData && (
          <p className="text-sm text-muted-foreground">
            No fundamentals data available for this company yet.
          </p>
        )}

        {fundamentals.ratios.length > 0 && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {fundamentals.ratios.map((r) => (
              <div key={r.metric} className="flex flex-col gap-0.5">
                <span className="text-xs text-muted-foreground">
                  {RATIO_LABELS[r.metric] ?? r.metric}
                </span>
                <span className="text-sm font-medium tabular-nums">
                  {formatRatio(r.metric, r.value)}
                </span>
              </div>
            ))}
          </div>
        )}

        {fundamentals.income_statement.length > 0 &&
          (() => {
            // Coverage is uneven period-by-period (Yahoo's Indian-ticker data
            // is "spotty and inconsistent" per Build_plan.md §H) — don't
            // assume every period has the same line items. Use the union of
            // keys across periods for the header, and show "—" per-cell
            // for whatever a specific period is missing, rather than
            // silently misaligning columns.
            const allKeys = Array.from(
              new Set(fundamentals.income_statement.flatMap((p) => Object.keys(p.line_items))),
            );
            return (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-xs text-muted-foreground">
                      <th className="py-1.5 pr-4 font-normal">Fiscal Year</th>
                      {allKeys.map((key) => (
                        <th key={key} className="py-1.5 pr-4 font-normal">
                          {LINE_ITEM_LABELS[key] ?? key}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {fundamentals.income_statement.map((period) => (
                      <tr key={period.period_end} className="border-b last:border-0">
                        <td className="py-1.5 pr-4 tabular-nums">{period.period_end}</td>
                        {allKeys.map((key) => (
                          <td key={key} className="py-1.5 pr-4 tabular-nums">
                            {key in period.line_items ? formatCrores(period.line_items[key]) : "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })()}

        <p className="text-xs text-muted-foreground">
          Best-effort, single-source data — always shown at low confidence. Missing fields are
          omitted rather than estimated.
        </p>
      </CardContent>
    </Card>
  );
}
