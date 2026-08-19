# API & DATA-SOURCE REGISTRY — `mlai`

> Companion to `Build_plan.md`. This is the authoritative list of every API/data source we may use, per data need, **with fallbacks so no single failure blocks us.**
> Two hard requirements from the founder: **(1) data must be correct, (2) it must be free.**
>
> ⚠️ **Verify-at-build-time rule (Screener.md §19):** free tiers, rate limits, and ToS change constantly. Every source below is a *candidate*; confirm availability + limits + redistribution terms in code before depending on it. "Verified" notes below reflect a planning-time check on 2026-08-11 and may drift.

---

## Legend — trust & access tier

| Mark | Meaning | Trust for correctness |
|---|---|---|
| ✅ **Official / free / no-auth** | Exchange or govt source, no key needed | **Highest** — source of truth |
| 🔑 **Free w/ account (broker)** | Free API tied to a demat/login; **daily token** | High — exchange-fed |
| 🆓 **Free tier (3rd-party)** | Public API, quota-limited | Medium — cross-check |
| ⚠️ **Scrape / ToS-gray / fragile** | Unofficial endpoint or library | Use with caution |
| ❌ **Not free for India / excluded** | Paid or India not in free tier | — |

**Correctness hierarchy (which wins in a conflict):**
`Official exchange (NSE/BSE, XBRL) > Broker API (Upstox/Angel/Fyers/Dhan) > Aggregator (yfinance/AlphaVantage) > Scraper libs`

---

## 1. Instruments Master & Symbol Mapping

| Source | Tier | Gives | Notes | Role |
|---|---|---|---|---|
| Upstox instruments dump | 🔑 | All instrument keys + metadata | Needed to address Upstox by `instrument_key` | **Primary** |
| Angel One SmartAPI scrip master | 🔑 | Symbol tokens | JSON master file, free | Fallback + cross-map |
| NSE symbol list / EQUITY_L.csv | ✅ | Canonical NSE symbols, ISIN | Free, no auth | Canonical map |

→ Populates `instrument_map` so every provider is addressable from one `asset`.

---

## 2. Universe (Nifty 500 & sector indices)

| Source | Tier | Gives | Notes | Role |
|---|---|---|---|---|
| NSE index constituents CSV (`ind_nifty500list.csv`) | ✅ | Nifty 500 members + sector | Free; refresh monthly (rebalances) | **Primary** |
| NSE sector index CSVs | ✅ | Bank/IT/Auto etc. members | For relative-strength-vs-sector | Primary |
| Derive from broker scrip master | 🔑 | Full tradable list | Filter to index if CSV fails | Fallback |

---

## 3. EOD Prices (OHLCV) — the price spine

| Source | Tier | Gives | Limits / caveat | Role |
|---|---|---|---|---|
| **NSE Bhavcopy** (`sec_bhavdata_full`) | ✅ | O/H/L/C, volume, **delivery qty & %** | EOD only; no auth → **unattended-safe** | **Guaranteed spine** |
| BSE Bhavcopy | ✅ | O/H/L/C, volume | EOD; free | Cross-check / BSE names |
| **Upstox historical (daily)** | 🔑 | OHLC + volume + OI | **Daily = 1yr lookback**; 1 instrument/req; daily token | **Preferred feed** |
| Angel One SmartAPI `getCandleData` | 🔑 | OHLC candles | Free w/ demat; daily token (TOTP) | **Broker fallback #1** |
| Fyers / Dhan history API | 🔑 | OHLC candles | Free w/ account | Broker fallback #2/#3 |
| yfinance (`.NS`/`.BO`) | ⚠️ | OHLC + adj close | Personal-use ToS; unofficial; **good for backfill** | Backfill / cross-check |
| jugaad-data / nsepython | ⚠️ | NSE historical, bhavcopy | Wraps NSE; fragile; convenience | Optional wrapper |
| ~~Zerodha Kite Connect~~ | ❌ | — | **Paid ₹2000/mo** | Excluded |
| ~~Twelve Data / Marketstack~~ | ❌ | — | **India not in free tier** (verified) | Excluded (free) |

**Redundancy chain:** `Upstox → Angel One → Bhavcopy (spine + reconcile) → yfinance (backfill)`.
**Correctness rule:** reconcile daily close across **two** sources; if divergence > 0.5%, flag `low-confidence` and prefer the official (Bhavcopy) value.
**Deep multi-year daily** (for P2 event engine): **accumulate Bhavcopy/Upstox daily bars from day 1** + one-time yfinance backfill.

---

## 4. Intraday / Quotes / LTP / Realtime *(P2 — not needed for EOD MVP)*

| Source | Tier | Gives | Notes | Role |
|---|---|---|---|---|
| Upstox quotes + WebSocket | 🔑 | LTP, full quote, live feed | Multi-instrument quote batch | **Primary (later)** |
| Angel One quote / WebSocket | 🔑 | LTP, live feed | Free | Fallback |
| Fyers / Dhan feed | 🔑 | Live feed | Free | Fallback |

---

## 5. Delivery % & Market Participation

| Source | Tier | Gives | Notes | Role |
|---|---|---|---|---|
| **NSE `sec_bhavdata_full`** | ✅ | Delivery qty, **delivery %**, trades | **Only reliable free source** — brokers don't give this | **Primary (sole)** |

→ Powers the "% of free float traded" volume philosophy (§9). No fallback exists free; if NSE format breaks, this metric degrades gracefully to `unavailable`.

---

## 6. Corporate Actions (splits / bonus / dividends / rights)

| Source | Tier | Gives | Notes | Role |
|---|---|---|---|---|
| NSE corporate-actions feed | ✅ | Ex-dates, ratios | Free (unofficial JSON) | **Primary** |
| BSE corporate-actions | ✅ | Ex-dates, ratios | Free | Cross-check |
| yfinance `.actions` | ⚠️ | Splits, dividends | Free; easy | Fallback / cross-check |

→ Drives price adjustment (correctness-critical). Reconcile NSE vs yfinance; a mismatch blocks adjustment until resolved (never silently mis-adjust).

---

## 7. Fundamentals (statements & ratios) — ⚠️ the biggest gap

No source offers **correct + free + complete** Indian fundamentals. Strategy = layered best-effort + flags, never fabricate.

| Source | Tier | Gives | Reality | Role |
|---|---|---|---|---|
| yfinance financials | ⚠️ | Income/BS/CF, some ratios | Coverage **spotty & inconsistent** for India | Best-effort primary |
| Alpha Vantage fundamentals | 🆓 | Income/BS/CF, overview | **~25 req/day free** (verified); some India via `BSE:` | Cross-check (tiny quota) |
| Financial Modeling Prep | 🆓 | Statements | Free ~250/day but **India largely paid** | Low priority |
| EODHD | 🆓→💵 | Statements/ratios | Free **20 calls/day** (verified); real data on paid feeds (see §12) | Paid upgrade path |
| **NSE/BSE XBRL filings** | ✅ | Official quarterly/annual results | **Authoritative** but parsing-heavy | **P2 parser (source of truth)** |
| Curated Nifty 500 core-fields set | ✅(ours) | Revenue/PAT/ROE/ROCE/D-E etc. | Manual/semi-auto seed for MVP reliability | **MVP guarantee** |
| ~~screener.in / Tickertape / Trendlyne / MoneyControl~~ | ❌ | rich fundamentals | **No free API; scraping violates ToS** | **Excluded** |

**Redundancy chain:** `curated seed (MVP) → yfinance → AlphaVantage/FMP cross-check → XBRL (P2 authoritative)`.
Every fundamental carries `source + as_of + confidence`; missing = shown as **"data unavailable,"** never guessed.
💵 **Want better fundamentals for money? See §12 — realistic verdict: ₹500/mo won't fix this; the real fix is ~₹1,700–5,000/mo (EODHD).**

---

## 8. News

| Source | Tier | Gives | Notes | Role |
|---|---|---|---|---|
| RSS: Moneycontrol, ET Markets, Business Standard, LiveMint | ✅ | Headlines + links + time | Free, **unlimited**, reliable | **Primary** |
| Google News RSS (per-company query) | ✅ | Company-specific headlines | Free; build query per symbol | Primary (targeted) |
| NSE/BSE corporate announcements | ✅ | Official filings/events | Authoritative event source | **Event primary** |
| GDELT 2.0 DOC API | 🆓 | Global news volume + tone | Free; good for spikes | Volume/tone signal |
| Marketaux | 🆓 | Entity-tagged news + sentiment | Free ~100/day (verify); India covered | Entity+sentiment enrich |
| NewsData.io | 🆓 | News + India filter | Free tier ~200 credits/day (verify) | Fallback enrich |
| Finnhub company-news | 🆓 | Company news + sentiment | 60/min free; mostly US, some India | Cross-check |
| ~~NewsAPI.org~~ | 🆓 | Headlines | 100/day, **non-commercial, 24h delayed** | Last resort |

**Redundancy chain:** `RSS + NSE/BSE announcements (backbone) → GDELT (volume) → Marketaux/NewsData (entity+sentiment)`, merged and **deduped by content hash**.

---

## 9. Sentiment & Event Classification

| Source | Tier | Gives | Notes | Role |
|---|---|---|---|---|
| **FinBERT** (local model) | ✅ free/offline | Finance-tuned sentiment | No API cost; run in job | **Primary** |
| VADER (local) | ✅ free/offline | Fast lexicon sentiment | Cheap baseline | Baseline |
| Our LLM layer | 🆓 (cost-capped) | Event type, nuance, "temporary vs structural" | Cache by content hash | Event classification |
| Marketaux / Finnhub sentiment | 🆓 | Provider sentiment | Free tiers | Cross-check |

→ Keeps sentiment **free and offline** by default; LLM only for nuanced event classification, cached hard.

---

## 10. Benchmark & Index Levels

| Source | Tier | Gives | Notes | Role |
|---|---|---|---|---|
| NSE index CSV / history | ✅ | Nifty 50/500, sector index levels | For relative-strength calcs | **Primary** |
| yfinance `^CRSLDX` (Nifty 500), `^NSEI` | ⚠️ | Index history | Free; backfill | Fallback |

---

## 11. Macro / Economic & Global *(future expansion, §29)*

| Source | Tier | Gives | Role |
|---|---|---|---|
| RBI / data.gov.in | ✅ | India macro | Future |
| FRED API | 🆓 (free key) | US/global macro | Future (US equities) |
| World Bank API | ✅ | Global indicators | Future |
| yfinance / Stooq | ⚠️ | US equities, FX, crypto proxy | Future markets |

---

## 12. Paid Upgrade Options — budget ~₹500/month (~$6)

> **Honest verdict:** ₹500/month does **not** buy a quality Indian **fundamentals** feed — which is our actual gap. Dedicated fundamentals feeds start at **~$20–60/mo (₹1,700–5,000)**. Prices/news are already solved for free, so paid price feeds add little. Below: what ₹500 realistically buys, and the smallest spend that genuinely fixes fundamentals if the budget can stretch. *(Prices verified 2026-08-11 where noted; re-confirm + check India coverage before paying.)*

### Within ₹500/mo (~$6)

| Option | ~Price | What it adds | Verdict |
|---|---|---|---|
| **RapidAPI "Indian Stock" fundamentals APIs** | ~₹400–800 | Ratios/statements (often resold screener/NSE data) | ⚠️ Variable quality, ToS risk sits with reseller. Usable as a **cheap fundamentals fallback** *only if cross-checked* vs yfinance/XBRL. Keep behind `FundamentalDataProvider`. **Verify.** |
| **Indian micro-VPS / managed cron** | ~₹350–500 | *Not data* — reliability: run the free official pipeline from an **Indian IP** (NSE is friendlier to in-country IPs), no free-tier cold starts, keep broker tokens refreshed | ✅ **Best ₹500 spend for correctness** of the free stack |
| **TrueData / GlobalDataFeeds "personal"** | ~₹500–800 | Authorized-vendor **realtime + historical NSE prices** | Reliable, but **prices are already free** → low marginal value. **Verify.** |

### Stretch tiers (best value-per-rupee if budget flexes) — *these actually fix fundamentals*

| Option | ~Price (₹) | What it adds | When to buy |
|---|---|---|---|
| Marketstack Basic | ~₹850 ($9.99) ✅ | EOD 10k req/mo; **India coverage unconfirmed**, no fundamentals until Business tier | Skip — marginal for us |
| **EODHD "All-World" EOD** | ~₹1,700 ($19.99) ✅ | Multi-year global EOD + *some* fundamentals; **great for future US/global expansion** | **Best single starter feed** |
| FMP Starter / Twelve Data Grow | ~₹1,900–2,500 ($22–29) | Financial statements; **Twelve Data Grow adds India** (free tier excludes it) | If fundamentals via yfinance prove too thin |
| **EODHD "Fundamentals Data Feed"** | ~₹5,000 ($59.99) ✅ | **The real fundamentals fix** — global statements/ratios | When fundamentals become the priority |

*(Excluded at any tier: Zerodha Kite Connect ₹2,000/mo data — brokers give this free elsewhere; screener.in/Tickertape/Trendlyne — no API sold.)*

### Recommendation
1. **If ₹500 is a hard cap:** either (a) plug a **RapidAPI Indian fundamentals API** in as a cross-checked fallback, or (b) — better for correctness — spend it on an **Indian micro-VPS** so the *free* official pipeline runs reliably.
2. **When you're ready to truly fix fundamentals**, the smallest meaningful spend is **~₹1,700 (EODHD All-World)** → **~₹5,000 (EODHD Fundamentals)**. Both are also global-ready, which serves the US/ETF/crypto expansion path.
3. Architecture already supports this: any of these drops in behind `FundamentalDataProvider` / `MarketDataProvider` with **zero rewrite** — so start free, pay only when a specific gap justifies it.

---

## Cross-Cutting Correctness & Redundancy Strategy

1. **Official-first:** exchange data (Bhavcopy, XBRL, NSE feeds) is the source of truth; brokers/aggregators fill gaps and add convenience.
2. **Two-source reconciliation** for prices and corporate actions; divergence → flag + prefer official.
3. **Ordered fallbacks in the provider registry** (`Build_plan.md` §F): each capability lists `[primary, fallback, …]`; a failed/empty/stale response cascades automatically.
4. **Never fabricate:** missing/low-confidence data is flagged in UI (`source + as_of + confidence`), never guessed — protects the "evidence over opinion" principle.
5. **Auth isolation:** broker daily-token lifecycles (Upstox/Angel/Fyers/Dhan) live inside each provider; the auth-free Bhavcopy spine guarantees the pipeline survives any token lapse.
6. **Quota-aware scheduling:** tiny-quota sources (Alpha Vantage 25/day) used only for targeted cross-checks, never bulk ingestion; bulk = official CSVs + broker APIs.
7. **ToS compliance:** scraping paid-content sources (screener.in, Tickertape, Trendlyne, MoneyControl bodies) is **excluded**; only their public RSS headlines are used.
8. **Provider-health logging** (`provider_fetch_log`) flags a source that starts failing so we switch before users notice.

---

## Summary — recommended stack per need

| Need | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|
| Instruments/map | Upstox dump | Angel scrip master | NSE CSV |
| Universe | NSE index CSV | broker scrip master | — |
| EOD prices | **Upstox daily** | **Angel One** | **NSE Bhavcopy** (+yfinance backfill) |
| Delivery % | NSE `sec_bhavdata_full` | — | — |
| Corporate actions | NSE feed | BSE feed | yfinance actions |
| Fundamentals | curated seed (MVP) | yfinance | AlphaVantage/FMP → **XBRL (P2)** |
| News | RSS + NSE/BSE announcements | GDELT | Marketaux/NewsData |
| Sentiment | FinBERT (local) | VADER | LLM / provider sentiment |
| Index levels | NSE index CSV | yfinance | — |

**Zero-cost, redundant, official-first, and correct-by-reconciliation** — with no dependency on any single provider staying free or online.

*Re-verify every free tier and ToS in code before relying on it.*
