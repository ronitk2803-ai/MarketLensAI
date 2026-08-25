const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    /** The backend's own {"detail": "..."} message, when the error body
     * parsed as JSON with one — only populated by apiFetchRaw callers
     * (auth), since that's the first place a user-facing distinction
     * between error reasons (wrong password vs. duplicate email) matters
     * enough to plumb through. */
    public detail?: string,
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

/** For endpoints that return a bare JSON body rather than the {data, meta}
 * envelope — auth (app/api/v1/auth.py) is the only current example, since
 * meta.source/meta.confidence are specifically about market-data
 * provenance and don't apply to an account action. */
async function apiFetchRaw<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, init);
  if (!res.ok) {
    const detail = await res
      .json()
      .then((body: unknown) =>
        typeof body === "object" && body !== null && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : undefined,
      )
      .catch(() => undefined);
    throw new ApiError(`Request to ${path} failed`, res.status, detail);
  }
  return res.json() as Promise<T>;
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

export interface SectorPe {
  trailing_pe: number | null;
  trailing_pe_source: "nse_index" | "peer_median" | null;
  trailing_pe_index_name: string | null;
  trailing_pe_sample_size: number;
  forward_median: number | null;
  forward_sample_size: number;
}

export interface Fundamentals {
  ratios: RatioValue[];
  income_statement: IncomeStatementPeriod[];
  sector_pe: SectorPe;
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

export interface OpportunityIndustry {
  code: string;
  name: string;
}

export function getOpportunityIndustries() {
  return apiFetch<OpportunityIndustry[]>("/opportunities/industries", {
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
  industry: string | null;
}

export function getOpportunities(screen: string, industry?: string) {
  const params = new URLSearchParams({ screen });
  if (industry) params.set("industry", industry);
  return apiFetch<OpportunityHit[]>(`/opportunities?${params.toString()}`, {
    next: { revalidate: 900 },
  });
}

export interface ScoreComponent {
  component: string;
  normalized_value: number | null;
  weight: number;
  contribution: number | null;
}

export interface ScoreInputs {
  rsi14: number | null;
  drawdown_pct: number | null;
  debt_to_equity: number | null;
  gross_margins: number | null;
  revenue_growth: number | null;
  earnings_growth: number | null;
  price_to_book: number | null;
  relative_volume: number | null;
  delivery_pct: number | null;
}

export interface Score {
  value: number | null;
  coverage: number;
  as_of: string;
  components: ScoreComponent[];
  inputs: ScoreInputs;
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

/** Account-backed as of P1 — membership lives server-side per user, so
 * every call needs the caller's access token; there's no anonymous
 * "give me quotes for these symbols" path anymore (see
 * app/services/watchlist.py's module docstring on the backend). Still the
 * {data, meta} envelope (apiFetch, not apiFetchRaw) — GET /watchlist
 * returns market-data provenance like every other data-reading endpoint;
 * only the add/remove actions below are bare-JSON like auth. */
export function getWatchlist(accessToken: string, deltaDays: number[]) {
  const params = new URLSearchParams({ deltas: deltaDays.join(",") });
  return apiFetch<WatchlistResponse>(`/watchlist?${params.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
}

export function addToWatchlist(accessToken: string, symbol: string) {
  return apiFetchRaw<{ status: string }>(`/watchlist/${encodeURIComponent(symbol)}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
}

export function removeFromWatchlist(accessToken: string, symbol: string) {
  return apiFetchRaw<{ status: string }>(`/watchlist/${encodeURIComponent(symbol)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
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

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
}

export interface AuthUser {
  id: number;
  email: string;
}

export function registerUser(email: string, password: string) {
  return apiFetchRaw<AuthTokens>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
}

export function loginUser(email: string, password: string) {
  return apiFetchRaw<AuthTokens>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
}

export function refreshTokens(refreshToken: string) {
  return apiFetchRaw<AuthTokens>("/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  });
}

export function logoutUser(refreshToken: string) {
  return apiFetchRaw<{ status: string }>("/auth/logout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  });
}

/** Server Components call this directly (not through a Route Handler) —
 * same as getCompany/getPrices/etc., per this app's existing convention
 * that Route Handlers only exist to bridge Client Components that can't
 * reach API_BASE_URL server-side. Reads the user from the backend's own
 * signature-verified token check rather than decoding the JWT locally, so
 * the frontend never needs to know the signing secret and login-state
 * display always reflects what the backend would actually accept. */
export async function getCurrentUser(accessToken: string): Promise<AuthUser | null> {
  try {
    return await apiFetchRaw<AuthUser>("/auth/me", {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

// Thesis Tracker (Build_plan.md §X.1) — bare JSON like auth above, not the
// {data, meta} envelope: a thesis is user-authored content plus a computed
// number, not market data with source/confidence to report.

export type ThesisStance = "bull" | "bear" | "neutral";
export type ThesisStatus = "active" | "challenged" | "invalidated" | "closed";
export type ThesisOperator = "gt" | "lt" | "gte" | "lte" | "eq";

export interface ThesisTrigger {
  id: number;
  metric: string;
  operator: ThesisOperator;
  threshold: number;
  description: string | null;
  currently_breached: boolean;
}

export interface ThesisEvent {
  id: number;
  trigger_id: number;
  metric: string;
  operator: ThesisOperator;
  threshold: number;
  fired_at: string;
  observed_value: number | null;
  note: string | null;
}

export interface ThesisSummary {
  id: number;
  symbol: string;
  exchange: string;
  asset_name: string;
  title: string;
  body: string;
  stance: ThesisStance;
  conviction: number;
  status: ThesisStatus;
  created_at: string;
}

export interface Thesis extends ThesisSummary {
  triggers: ThesisTrigger[];
}

export interface ThesisDetail extends Thesis {
  events: ThesisEvent[];
}

export interface CreateThesisPayload {
  symbol: string;
  title: string;
  body: string;
  stance: ThesisStance;
  conviction: number;
  triggers: {
    metric: string;
    operator: ThesisOperator;
    threshold: number;
    description?: string;
  }[];
}

export interface UpdateThesisPayload {
  title?: string;
  body?: string;
  stance?: ThesisStance;
  conviction?: number;
  status?: ThesisStatus;
}

/** Server Components call these directly, same reasoning as getCurrentUser
 * above — only the mutations need a Route Handler (app/api/theses/*),
 * since those come from Client Component forms that can't reach
 * API_BASE_URL or read the session cookie themselves. */
export function getTheses(accessToken: string) {
  return apiFetchRaw<ThesisSummary[]>("/theses", {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
}

export function getThesis(accessToken: string, id: number) {
  return apiFetchRaw<ThesisDetail>(`/theses/${id}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
}

export function createThesis(accessToken: string, payload: CreateThesisPayload) {
  return apiFetchRaw<Thesis>("/theses", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
}

export function updateThesis(accessToken: string, id: number, payload: UpdateThesisPayload) {
  return apiFetchRaw<Thesis>(`/theses/${id}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
}

export function deleteThesis(accessToken: string, id: number) {
  return apiFetchRaw<{ status: string }>(`/theses/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
}

// Portfolio (Build_plan.md P1, multi-broker CSV/Excel import) — bare JSON
// like Thesis above: a holding is user-authored quantity/avg_cost plus a
// computed P&L, not market data with source/confidence to report.

export type PortfolioBroker = "manual" | "zerodha" | "upstox";

/** One underlying lot behind a consolidated PortfolioHolding — a user can
 * hold the same asset across multiple demat accounts plus a manual entry;
 * each is a separate row the backend sums into the consolidated totals
 * below, so this is what edit/delete actually target. */
export interface PortfolioLot {
  holding_id: number;
  broker: PortfolioBroker;
  quantity: number;
  avg_cost: number;
}

export interface PortfolioHolding {
  symbol: string;
  exchange: string;
  asset_name: string;
  quantity: number;
  avg_cost: number;
  last_price: number | null;
  as_of: string | null;
  market_value: number | null;
  cost_basis: number;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  lots: PortfolioLot[];
}

export interface PortfolioTotals {
  cost_basis: number;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  holdings_priced: number;
  holdings_total: number;
}

export interface Portfolio {
  holdings: PortfolioHolding[];
  totals: PortfolioTotals;
}

export interface AddHoldingPayload {
  symbol: string;
  quantity: number;
  avg_cost: number;
}

export interface UpdateHoldingPayload {
  quantity?: number;
  avg_cost?: number;
}

export interface PortfolioImportRowResult {
  row_number: number;
  symbol: string;
  status: "imported" | "skipped";
  reason: string | null;
}

export interface PortfolioImportSummary {
  imported: number;
  skipped: number;
  rows: PortfolioImportRowResult[];
}

/** Server Components call this directly, same as getTheses. */
export function getPortfolio(accessToken: string) {
  return apiFetchRaw<Portfolio>("/portfolio", {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
}

export function addHolding(accessToken: string, payload: AddHoldingPayload) {
  return apiFetchRaw<PortfolioHolding>("/portfolio", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
}

export function updateHolding(accessToken: string, id: number, payload: UpdateHoldingPayload) {
  return apiFetchRaw<PortfolioHolding>(`/portfolio/${id}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
}

export function deleteHolding(accessToken: string, id: number) {
  return apiFetchRaw<{ status: string }>(`/portfolio/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
}

/** `formData` is forwarded as-is from the Route Handler that received it
 * from the browser — apiFetchRaw doesn't force a Content-Type, so `fetch`
 * sets the correct multipart boundary itself. Don't set Content-Type
 * manually here; it would omit the boundary parameter and break parsing. */
export function importPortfolioCsv(accessToken: string, formData: FormData) {
  return apiFetchRaw<PortfolioImportSummary>("/portfolio/import", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
    body: formData,
    cache: "no-store",
  });
}
