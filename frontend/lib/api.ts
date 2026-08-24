const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface Meta {
  as_of: string;
  source: string;
  confidence: "high" | "low";
}

interface Envelope<T> {
  data: T;
  meta: Meta;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<Envelope<T>> {
  const res = await fetch(`${API_BASE_URL}${path}`, init);
  if (!res.ok) {
    throw new ApiError(`Request to ${path} failed`, res.status);
  }
  return res.json() as Promise<Envelope<T>>;
}

export interface HealthStatus {
  status: string;
}

export function getHealth() {
  return apiFetch<HealthStatus>("/health").then((e) => e.data);
}

export interface AssetSearchResult {
  symbol: string;
  exchange: string;
  name: string;
  isin: string | null;
}

export function searchAssets(query: string) {
  return apiFetch<AssetSearchResult[]>(`/assets/search?q=${encodeURIComponent(query)}`).then(
    (e) => e.data,
  );
}

export interface CompanyHeader {
  symbol: string;
  exchange: string;
  name: string;
  sector: string | null;
  industry: string | null;
  latest_price: {
    date: string | null;
    close: number | null;
    change_pct: number | null;
  };
}

export type PriceRange = "1m" | "3m" | "6m" | "1y" | "5y";

export function getCompany(symbol: string) {
  return apiFetch<CompanyHeader>(`/companies/${encodeURIComponent(symbol)}`, {
    next: { revalidate: 60 },
  });
}

export interface PriceBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export function getPrices(symbol: string, range: PriceRange = "1y") {
  return apiFetch<PriceBar[]>(`/companies/${encodeURIComponent(symbol)}/prices?range=${range}`, {
    next: { revalidate: 60 },
  });
}

export interface CorporateAction {
  ex_date: string;
  type: string;
  ratio: number | null;
  amount: number | null;
}

export function getCorporateActions(symbol: string) {
  return apiFetch<CorporateAction[]>(`/companies/${encodeURIComponent(symbol)}/corporate-actions`, {
    next: { revalidate: 3600 },
  });
}

export interface TechnicalSnapshot {
  as_of: string | null;
  close: number | null;
  dma20: number | null;
  dma50: number | null;
  dma100: number | null;
  dma200: number | null;
  rsi14: number | null;
  macd_line: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  volatility20: number | null;
  drawdown_pct: number | null;
}

export interface TechnicalSeries {
  dates: string[];
  close: number[];
  dma20: (number | null)[];
  dma50: (number | null)[];
  dma100: (number | null)[];
  dma200: (number | null)[];
}

export interface Technicals {
  latest: TechnicalSnapshot;
  series: TechnicalSeries;
}

export interface RatioValue {
  metric: string;
  value: number;
  source: string;
  confidence: "high" | "low";
}

export interface IncomeStatementPeriod {
  period_end: string;
  period_type: string;
  line_items: Record<string, number>;
}

export interface Fundamentals {
  ratios: RatioValue[];
  income_statement: IncomeStatementPeriod[];
}

export function getFundamentals(symbol: string) {
  return apiFetch<Fundamentals>(`/companies/${encodeURIComponent(symbol)}/fundamentals`, {
    next: { revalidate: 3600 },
  });
}

export interface NewsItem {
  url: string;
  source: string;
  published_at: string;
  title: string;
}

export function getNews(symbol: string) {
  return apiFetch<NewsItem[]>(`/companies/${encodeURIComponent(symbol)}/news`, {
    next: { revalidate: 300 },
  });
}

export interface OpportunityScreen {
  id: string;
  label: string;
}

export function getOpportunityScreens() {
  return apiFetch<OpportunityScreen[]>("/opportunities/screens", {
    next: { revalidate: 3600 },
  });
}

export interface OpportunityHit {
  symbol: string;
  exchange: string;
  name: string;
  screen_id: string;
  metrics: Record<string, number>;
  rank: number;
  opportunity_score: number | null;
  /** Trailing ~30 sessions of corporate-action-adjusted closes, oldest first. */
  spark: number[];
}

export function getOpportunities(screen: string) {
  return apiFetch<OpportunityHit[]>(`/opportunities?screen=${encodeURIComponent(screen)}`, {
    next: { revalidate: 900 },
  });
}

export interface ScoreComponent {
  component: string;
  normalized_value: number | null;
  weight: number;
  contribution: number | null;
}

export interface Score {
  value: number | null;
  coverage: number;
  as_of: string;
  components: ScoreComponent[];
}

export function getScore(symbol: string) {
  return apiFetch<Score>(`/companies/${encodeURIComponent(symbol)}/score`, {
    next: { revalidate: 900 },
  });
}

export function getTechnicals(symbol: string, range: PriceRange = "1y") {
  return apiFetch<Technicals>(`/companies/${encodeURIComponent(symbol)}/technicals?range=${range}`, {
    next: { revalidate: 60 },
  });
}


export interface WatchlistRangeStat {
  high: number;
  low: number;
  /** 0..1 position of the latest close between low and high; null if flat. */
  position: number | null;
  since: string;
}

export interface WatchlistQuote {
  symbol: string;
  exchange: string;
  name: string;
  as_of: string | null;
  close: number | null;
  /** Keyed by the requested trading-session window, e.g. "7" -> +4.2. */
  deltas: Record<string, number>;
  all_time: WatchlistRangeStat | null;
  week_52: WatchlistRangeStat | null;
  spark: number[];
}

export interface WatchlistResponse {
  quotes: WatchlistQuote[];
  unknown_symbols: string[];
}

export function getWatchlistQuotes(symbols: string[], deltaDays: number[]) {
  const params = new URLSearchParams({
    symbols: symbols.join(","),
    deltas: deltaDays.join(","),
  });
  return apiFetch<WatchlistResponse>(`/watchlist/quotes?${params.toString()}`).then((e) => e.data);
}

export interface DayCandle {
  open: number;
  high: number;
  low: number;
  /** The live LTP — this candle is still forming. */
  close: number;
  volume: number | null;
}

export interface LiveQuote {
  symbol: string;
  exchange: string;
  ltp: number;
  previous_close: number | null;
  change_pct: number | null;
  as_of: string;
  /** Provider's own session state, e.g. "REGULAR" | "CLOSED" | "PRE" | "POST". */
  market_state: string | null;
  /** Today's forming OHLCV; null unless the full OHLC is available. */
  day_candle: DayCandle | null;
}

export interface AiSummary {
  summary: string;
  generated_at: string;
}

/** Cache-only read — never triggers generation, safe on every page load. */
export function getAiSummary(symbol: string) {
  return apiFetch<AiSummary | null>(`/companies/${encodeURIComponent(symbol)}/ai-summary`, {
    next: { revalidate: 60 },
  });
}

/** The button's action — the only thing that can spend an LLM call, and
 * only when the cached summary is actually out of date (see backend
 * app/services/company_summary.py). */
export function generateAiSummary(symbol: string) {
  return apiFetch<AiSummary>(`/companies/${encodeURIComponent(symbol)}/ai-summary`, {
    method: "POST",
    cache: "no-store",
  }).then((e) => e.data);
}

export function getLiveQuotes(symbols: string[]) {
  const params = new URLSearchParams({ symbols: symbols.join(",") });
  return apiFetch<LiveQuote[]>(`/quotes?${params.toString()}`, { cache: "no-store" });
}
