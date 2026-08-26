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
    "Price ÷ earnings per share over the last 12 months. How many years of current profit it'd take to earn back the share price, all else equal. Higher usually means the market expects faster growth (or the stock is expensive); compare within the same industry, not across very different businesses. The line below it is exactly that comparison — a named index (e.g. \"Nifty Financial Services 16.04\") is NSE's own official sector P/E, computed across that index's full constituent list, the most reliable figure available. \"Sector median (n=...)\" is this app's own fallback for the couple of industries with no matching Nifty sectoral index — a median across other same-industry companies it has data for (loss-making companies excluded, since a negative P/E isn't a valuation multiple in the same sense), hidden below a minimum sample since two companies isn't really a sector figure yet.",
  forwardPE:
    "Same idea as trailing P/E, but using analysts' estimated earnings for the year ahead instead of the last 12 months. A forward P/E much lower than the trailing one implies the market expects earnings to grow — and is only as reliable as the estimate it's built on. NSE doesn't publish a forward-looking sector P/E, so the comparison below it is always this app's own peer median, same rule as trailing P/E's fallback.",
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
  marketCap:
    "Share price × total shares outstanding — what it would cost, at the current price, to buy every share of the company. The standard measure of company size used to compare businesses regardless of their individual share price.",
  sharesOutstanding:
    "The total number of shares the company has issued. Includes shares held by promoters/founders and large strategic holders, not just what trades day to day — for that, see free float.",
  floatShares:
    "Free float: the shares actually held by the public and available to trade, excluding promoter/founder and other strategic holdings that rarely change hands. A small float relative to shares outstanding means fewer shares are really liquid, which can make the price move more sharply on modest buying or selling.",
  marketCapCategory:
    "Large/Mid/Small-cap, from market cap against fixed rupee thresholds — a common shorthand, not SEBI's official classification. SEBI ranks every listed company by market cap and re-publishes the large/mid/small cutoffs by rank (top 100 / next 150 / the rest) twice a year; this app doesn't rank the whole listed market, so this is an approximation for a quick sense of scale, not the regulatory ranking.",

  // Technical panel — same "explain the jargon, don't grade it" rule.
  dma: "Simple moving average of the closing price over the last N sessions — the average smoothed to filter out day-to-day noise. Price above its DMA is often read as an uptrend, below as a downtrend; the more sessions in the average, the slower it reacts to recent moves.",
  rsi: "Relative Strength Index (14-day): a 0–100 momentum gauge based on the size of recent up-moves versus down-moves. Above 70 is conventionally called \"overbought,\" below 30 \"oversold\" — shorthand for \"has moved a lot, in one direction, recently,\" not a signal that a reversal is imminent.",
  macd: "Moving Average Convergence/Divergence: the gap between a fast and a slow moving average of price, used to read momentum and potential trend shifts. The histogram is that line's own distance from its signal line — positive and growing suggests strengthening momentum, negative and growing suggests weakening.",
  volatility: "Annualized standard deviation of daily returns — how much the price has been swinging, scaled to a yearly figure so it's comparable across stocks. Higher means bigger, more frequent price swings in either direction; it says nothing about direction, only about the size of the moves.",
  drawdown: "How far the current price sits below its most recent peak, in percent. A running measure of \"how much would you have lost if you bought at the top and held,\" not a prediction of further downside.",

  // Opportunity Score components — each blends 1-2 raw inputs (shown below
  // the bar) into a 0-100 normalized value, then whichever components the
  // company's industry profile applies are weighted together. "Why did
  // this land here" should always be answerable by reading the raw numbers
  // underneath, not by trusting the bar alone.
  valuation:
    "How cheap or expensive the stock looks against its own accounting net worth, using price-to-book. A lower P/B scores higher here — it says nothing about whether that cheapness is deserved (a low P/B can mean bargain, or it can mean the market doubts the assets are worth what the books say).",
  fundamental_quality:
    "Balance-sheet and margin health: less debt relative to equity, and higher gross margins, both score higher. A read on how financially sound and efficiently the business runs, independent of what the stock currently costs. Not applied to lenders, where borrowing is the business model rather than a risk signal and the margin figures don't mean the same thing.",
  earnings_valuation:
    "How cheap or expensive the stock looks against its own profits, using trailing price-to-earnings. A lower P/E scores higher. A loss-making company gets no score here rather than a flattering one — it doesn't have a cheap multiple, it has no multiple.",
  growth:
    "How fast revenue and earnings have been growing year over year. Faster growth scores higher — but growth alone doesn't say whether it's profitable growth (pair with fundamental quality) or already priced in (pair with valuation).",
  technical_setup:
    "Where the price sits relative to its own recent trading range: a deeper drawdown from the recent peak combined with a lower (more \"oversold\") RSI scores higher here — this component rewards a beaten-down setup, not a strong one. It reads the chart, not the business.",
  participation:
    "How much trading interest the stock has seen lately: volume relative to its own 20-day average, and the share of that volume settled as actual delivery (not intraday trading). Higher scores mean more — and more \"real\" — market interest, not a judgment on where the price goes next.",
  historical_fall:
    "A stretch where the stock closed 20% or more below its own running peak, measured on corporate-action-adjusted closes. It starts at that peak, bottoms at its lowest close, and ends the first day the price closes back at the peak — so \"recovered\" means it got back to where it was, which is what someone who bought at the top actually experienced. A fall still in progress has no recovery time; it is shown as ongoing rather than as a slow recovery. Past falls are listed as a record of what happened, not an indication of what will.",
};

export function kpiDescription(metric: string): string | undefined {
  return KPI_GLOSSARY[metric];
}
