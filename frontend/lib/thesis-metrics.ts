/**
 * Must stay in sync with backend/app/services/thesis_metrics.py's
 * METRIC_KEYS — there's no shared codegen between the two, so a new
 * resolver added there needs a matching entry here to be selectable from
 * the create-thesis form. The backend is still the source of truth for
 * what's actually valid (POST /theses re-validates against METRIC_KEYS);
 * this list only drives the dropdown.
 */
export const THESIS_METRICS: { value: string; label: string }[] = [
  { value: "debt_to_equity", label: "Debt / Equity" },
  { value: "price_to_book", label: "P / B" },
  { value: "trailing_pe", label: "P/E (TTM)" },
  { value: "forward_pe", label: "Forward P/E" },
  { value: "gross_margins", label: "Gross margin" },
  { value: "operating_margins", label: "Operating margin" },
  { value: "profit_margins", label: "Net margin" },
  { value: "revenue_growth", label: "Revenue growth" },
  { value: "earnings_growth", label: "Earnings growth" },
  { value: "return_on_equity", label: "ROE" },
  { value: "return_on_assets", label: "ROA" },
  { value: "beta", label: "Beta" },
  { value: "rsi14", label: "RSI (14)" },
  { value: "drawdown_pct", label: "Drawdown from peak" },
  { value: "volatility20", label: "Volatility (20d)" },
  { value: "close", label: "Price" },
  { value: "dma20_gap_pct", label: "Price vs 20-day average" },
  { value: "dma50_gap_pct", label: "Price vs 50-day average" },
  { value: "dma100_gap_pct", label: "Price vs 100-day average" },
  { value: "dma200_gap_pct", label: "Price vs 200-day average" },
];

export const THESIS_OPERATORS: { value: string; label: string }[] = [
  { value: "gt", label: "> (above)" },
  { value: "lt", label: "< (below)" },
  { value: "gte", label: "≥ (at or above)" },
  { value: "lte", label: "≤ (at or below)" },
  { value: "eq", label: "= (equal to)" },
];
