# Data Strategy — `mlai`

> How we source, store, refresh, and trust data. Expands `Build_plan.md` §G–I and §19–21 of the brief. The exhaustive source list lives in [`../API_Sources.md`](../API_Sources.md).

## Principles
1. **Free-first.** Budget ~₹0. Build entirely on free sources; add paid feeds later only when a specific gap justifies it, behind the same provider interface (zero rewrite).
2. **Correct over complete.** Prefer official/authoritative sources; reconcile across two sources; **never fabricate** — missing data is flagged.
3. **Store only what earns its place.** Persist what reduces repeat API calls or powers analysis; avoid millions of useless rows.
4. **Compute, don't fetch.** Derive indicators locally from stored prices.
5. **Provenance always.** Every fact carries `source + as_of + confidence`.

## Source strategy (summary — full detail in API_Sources.md)
| Need | Primary | Fallbacks |
|---|---|---|
| Prices (EOD) | Upstox daily | Angel One → NSE Bhavcopy (spine) → yfinance backfill |
| Live (today) | Upstox quotes/WebSocket | Angel/Fyers/Dhan |
| Delivery % | NSE `sec_bhavdata_full` | *(only free source)* |
| Corporate actions | NSE feed | BSE → yfinance |
| Fundamentals | curated seed (MVP) | yfinance → AV/FMP → **XBRL (P2)** |
| News | RSS + NSE/BSE filings | GDELT → Marketaux/NewsData |
| Sentiment | FinBERT (local) | VADER → LLM / provider |

**Correctness hierarchy:** Official exchange (NSE/BSE, XBRL) > Broker API (Upstox/Angel/Fyers/Dhan) > Aggregator (yfinance/AlphaVantage) > Scraper libs.

**Excluded:** paid-only-for-India free tiers (Twelve Data, Marketstack for fundamentals), and ToS-violating scrapes (screener.in, Tickertape, Trendlyne, MoneyControl bodies — only their public RSS headlines are used).

## Storage policy (decisions D-005/D-006)
- **Own PostgreSQL holds full daily history**: `O, H, L, C, Volume, OI, delivery qty & %` per stock per day, corporate-action-adjusted.
- **Live data only for the current day** (from Upstox); the EOD job writes the final daily bar into the DB.
- Full bars (not OHLC-only) because past comparison, the volume philosophy, and candlestick charts require them; storage cost is negligible.
- Charts render **adjusted candlesticks with visible split/bonus/dividend markers** (decision D-007).

## Volume philosophy
Raw volume alone is misleading. Where data permits, use **normalized** metrics: volume/shares-outstanding, volume/free-float, relative volume vs average, delivery %, turnover. Language must be precise: it's **"% of free float traded,"** not "% of investors who traded" (the same shares change hands multiple times).

## Caching & freshness
Every external read: **request → cache lookup → freshness check → serve if valid → refresh only if stale.**
- TTLs: EOD prices valid until next trading session; fundamentals quarterly; news hourly; profile weekly; instruments daily.
- MVP cache = Postgres (`provider_fetch_log` + stored data); Redis only when a measured need appears.
- Trading-calendar aware (no refresh on holidays).
- Batch + incremental: one daily job for the whole universe; only changed rows updated.

## Corporate-action adjustment
- `corporate_action` (splits/bonus/dividends/rights) sourced from NSE/BSE (+ yfinance cross-check).
- Adjustment applied **before** indicators and charts. Reconcile sources; a mismatch **blocks** adjustment until resolved (never silently mis-adjust).

## Fundamentals — the known gap
No free source is correct + complete for Indian fundamentals. Strategy:
1. **MVP:** curated Nifty 500 core-fields seed + yfinance best-effort, everything flagged with confidence.
2. **Cross-check:** Alpha Vantage / FMP within their tiny free quotas.
3. **P2 authoritative:** parse NSE/BSE **XBRL** filings.
4. **Paid path (later):** EODHD Fundamentals (~₹5,000/mo) behind `FundamentalDataProvider`. Note: ~₹500/mo does **not** solve this.

## Auth & reliability
- Broker daily-token lifecycles live inside each provider. The **auth-free NSE Bhavcopy spine** guarantees the pipeline survives any token lapse.
- `provider_fetch_log` flags a failing source early so we switch before users notice.

*See also: [`../API_Sources.md`](../API_Sources.md), [`architecture.md`](architecture.md), [`decision_log.md`](decision_log.md).*
