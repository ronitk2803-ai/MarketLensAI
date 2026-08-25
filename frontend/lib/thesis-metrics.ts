/**
 * Must stay in sync with backend/app/services/metric_registry.py's
 * METRIC_KEYS — there's no shared codegen between the two, so a new
 * resolver added there needs a matching entry here to be selectable from
 * the create-thesis form. The backend is still the source of truth for
 * what's actually valid (POST /theses re-validates against METRIC_KEYS);
 * this list only drives the dropdown.
 *
 * The registry is now also served at GET /screener/metrics with units, and
 * the advanced screener's builder reads it from there rather than keeping
 * a second copy. Rewiring this form to do the same is the follow-up that
 * would finally remove this duplication.
 *
 * Labels carry their unit because Yahoo isn't internally consistent:
 * debt_to_equity is a percentage (23.8 means 0.24x) while growth and
 * margins are fractions (0.15 means 15%). An unlabelled threshold box let
 * a user type "-30" for a drawdown and silently mean -3000%.
 */
export const THESIS_METRICS: { value: string; label: string }[] = [
  { value: "debt_to_equity", label: "Debt / Equity (%)" },
  { value: "price_to_book", label: "P / B (x)" },
  { value: "trailing_pe", label: "P/E (TTM) (x)" },
  { value: "forward_pe", label: "Forward P/E (x)" },
  { value: "gross_margins", label: "Gross margin (fraction, 0.15 = 15%)" },
  { value: "operating_margins", label: "Operating margin (fraction)" },
  { value: "profit_margins", label: "Net margin (fraction)" },
  { value: "revenue_growth", label: "Revenue growth (fraction)" },
  { value: "earnings_growth", label: "Earnings growth (fraction)" },
  { value: "return_on_equity", label: "ROE (fraction)" },
  { value: "return_on_assets", label: "ROA (fraction)" },
  { value: "beta", label: "Beta" },
  { value: "rsi14", label: "RSI (14)" },
  { value: "drawdown_pct", label: "Drawdown from peak (%)" },
  { value: "volatility20", label: "Volatility (20d, fraction)" },
  { value: "relative_volume", label: "Relative volume (x)" },
  { value: "delivery_pct", label: "Delivery (%)" },
  { value: "close", label: "Price (₹)" },
  { value: "change_5d_pct", label: "5-day price change (%)" },
  { value: "change_10d_pct", label: "10-day price change (%)" },
  { value: "change_15d_pct", label: "15-day price change (%)" },
  { value: "change_30d_pct", label: "30-day price change (%)" },
  { value: "change_60d_pct", label: "60-day price change (%)" },
  { value: "change_90d_pct", label: "90-day price change (%)" },
  { value: "dma20_gap_pct", label: "Price vs 20-day average (%)" },
  { value: "dma50_gap_pct", label: "Price vs 50-day average (%)" },
  { value: "dma100_gap_pct", label: "Price vs 100-day average (%)" },
  { value: "dma200_gap_pct", label: "Price vs 200-day average (%)" },
];

export const THESIS_OPERATORS: { value: string; label: string }[] = [
  { value: "gt", label: "> (above)" },
  { value: "lt", label: "< (below)" },
  { value: "gte", label: "≥ (at or above)" },
  { value: "lte", label: "≤ (at or below)" },
  { value: "eq", label: "= (equal to)" },
];
