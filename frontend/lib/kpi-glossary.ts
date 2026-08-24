/**
 * Plain-language descriptions for the ratios/metrics shown around the app —
 * what it is, how to read it, and why it matters. Keyed by the same field
 * names the backend already uses (Yahoo's own field names for the
 * fundamentals ratios), so a lookup is a single object access, not a
 * parallel mapping that can drift out of sync with RATIO_LABELS.
 *
 * Deliberately explanatory, not prescriptive: a KPI's "good" range depends
 * on the industry (a capital-intensive utility and an asset-light software
 * company have structurally different debt/equity, margins, ROE), so these
 * describe what the number means rather than asserting a universal
 * threshold — consistent with the rest of the app never rendering opinion
 * as fact (product_principles.md).
 */
export const KPI_GLOSSARY: Record<string, string> = {
  trailingPE:
    "Price ÷ earnings per share over the last 12 months. How many years of current profit it'd take to earn back the share price, all else equal. Higher usually means the market expects faster growth (or the stock is expensive); compare within the same industry, not across very different businesses.",
  forwardPE:
    "Same idea as trailing P/E, but using analysts' estimated earnings for the year ahead instead of the last 12 months. A forward P/E much lower than the trailing one implies the market expects earnings to grow — and is only as reliable as the estimate it's built on.",
  priceToBook:
    "Price ÷ book value (net assets) per share. Below 1 means the stock trades for less than its accounting net worth — sometimes a bargain, sometimes a sign the market doubts those assets are worth what the books say. More meaningful for asset-heavy businesses (banks, industrials) than for asset-light ones (software).",
  debtToEquity:
    "Total debt ÷ shareholder equity, as a percentage. How much of the company is funded by borrowing versus owners' capital. Higher means more financial leverage — it can amplify returns in good years, but also means more fixed obligations to service if earnings fall. \"Normal\" varies a lot by industry (utilities and banks typically run much higher than software companies).",
  grossMargins:
    "Gross profit ÷ revenue. What's left after the direct cost of making the product or delivering the service, before overhead, R&D, and marketing. A rough gauge of pricing power and cost efficiency at the most basic level.",
  operatingMargins:
    "Operating income ÷ revenue. What's left after *all* running costs — cost of goods, overhead, R&D, marketing — but before interest and tax. Shows how efficiently the core business itself is run, independent of how it's financed.",
  profitMargins:
    "Net income ÷ revenue. What's actually left for shareholders out of every rupee of sales, after everything — operating costs, interest, tax. The bottom-line efficiency number, but it can swing on one-off items (asset sales, write-offs) that operating margin doesn't show.",
  revenueGrowth:
    "Year-over-year change in revenue. Whether the business is actually getting bigger. Growth alone isn't the whole story — it matters whether that growth is also profitable (see margins) or coming at a cost.",
  earningsGrowth:
    "Year-over-year change in earnings (net income). Tends to be noisier than revenue growth, since profit is more sensitive to one-off costs, tax changes, and margin swings — a single bad or good quarter can distort it more than revenue.",
  returnOnEquity:
    "Net income ÷ shareholder equity. How much profit the company generates per rupee shareholders have invested. A widely used efficiency measure, but high ROE can also come from high debt (leverage) rather than genuine operating strength — worth reading alongside debt/equity, not alone.",
  returnOnAssets:
    "Net income ÷ total assets. How efficiently the company turns everything it owns — not just shareholder capital, but borrowed money too — into profit. Less sensitive to leverage than ROE, which makes it a useful cross-check against it.",
  beta:
    "How much this stock has historically moved relative to the broader market. Above 1 means it has tended to swing more than the market (in both directions); below 1, less. It's a measure of historical volatility relative to the market, not a prediction of future risk or return.",

  // Technical panel — same "explain the jargon, don't grade it" rule.
  dma: "Simple moving average of the closing price over the last N sessions — the average smoothed to filter out day-to-day noise. Price above its DMA is often read as an uptrend, below as a downtrend; the more sessions in the average, the slower it reacts to recent moves.",
  rsi: "Relative Strength Index (14-day): a 0–100 momentum gauge based on the size of recent up-moves versus down-moves. Above 70 is conventionally called \"overbought,\" below 30 \"oversold\" — shorthand for \"has moved a lot, in one direction, recently,\" not a signal that a reversal is imminent.",
  macd: "Moving Average Convergence/Divergence: the gap between a fast and a slow moving average of price, used to read momentum and potential trend shifts. The histogram is that line's own distance from its signal line — positive and growing suggests strengthening momentum, negative and growing suggests weakening.",
  volatility: "Annualized standard deviation of daily returns — how much the price has been swinging, scaled to a yearly figure so it's comparable across stocks. Higher means bigger, more frequent price swings in either direction; it says nothing about direction, only about the size of the moves.",
  drawdown: "How far the current price sits below its most recent peak, in percent. A running measure of \"how much would you have lost if you bought at the top and held,\" not a prediction of further downside.",
};

export function kpiDescription(metric: string): string | undefined {
  return KPI_GLOSSARY[metric];
}
