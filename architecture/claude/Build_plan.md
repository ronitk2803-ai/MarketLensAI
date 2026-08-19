# BUILD PLAN — Investment Intelligence Platform (codename: `mlai`)

> Planning document only. No application code is written yet.
> Source of truth for scope: `Screener.md`. This plan operationalizes it.
> **Project codename `mlai`** is used in all code/namespaces so the final brand is chosen later with zero refactoring. No discussed brand name is hard-coded.
>
> **v2 of this plan.** Changes from v1: (1) **Upstox** adopted as the preferred market-data provider (user has free Upstox API access); (2) recommended features — **Thesis Tracker**, provenance, score snapshotting, peer normalization, provider-health — promoted from suggestions to first-class scope with mini-specs; (3) expanded detail throughout.

---

## Table of Contents
- [0. Status & Repository Reality](#0-status--repository-reality)
- [A. Repository Structure](#a-recommended-repository-structure)
- [B. Technology Decisions & Alternatives](#b-technology-decisions--alternatives)
- [C. Database Architecture](#c-database-architecture)
- [D. Backend Architecture](#d-backend-architecture)
- [E. Frontend Architecture](#e-frontend-architecture)
- [F. Data Provider Abstraction](#f-data-provider-abstraction)
- [G. Indian Market Data Strategy (Upstox-first)](#g-initial-indian-market-data-strategy-upstox-first)
- [H. Free/Low-Cost Data-Source Feasibility](#h-free--low-cost-data-source-feasibility-assessment)
- [I. Caching Strategy](#i-caching-strategy)
- [J. API Strategy](#j-api-strategy)
- [K. Opportunity Engine](#k-opportunity-engine-architecture)
- [L. Scoring Engine](#l-scoring-engine-architecture)
- [M. Industry-Specific Scoring](#m-industry-specific-scoring-design)
- [N. AI Architecture](#n-ai-architecture)
- [O. Authentication](#o-authentication-approach)
- [P. Security](#p-security-considerations)
- [Q. MVP Scope](#q-mvp-scope)
- [R. P0/P1/P2 Priorities](#r-p0--p1--p2-feature-priorities)
- [S. Implementation Sequence](#s-exact-implementation-sequence)
- [T. Complexity Per Feature](#t-estimated-complexity-per-feature)
- [U. Risks / Blockers](#u-risks--blockers)
- [V. Questions To Resolve Before Coding](#v-questions-that-must-be-resolved-before-coding)
- [W. Definition of Done — MVP](#w-definition-of-done--mvp)
- [X. Feature Mini-Specs (added features)](#x-feature-mini-specs)

---

## 0. Status & Repository Reality

- Current repo contents: `Screener.md` only. **Not yet a git repository.**
- First implementation action (post-approval): `git init` + scaffold + docs skeleton.
- Dev environment: local on Windows; deploy to free-tier cloud.
- User assets available: **Upstox developer API access (free)** — see §G.

---

## A. Recommended Repository Structure

Monorepo. Backend and frontend are separate apps; docs at root.

```
mlai/
├─ docs/
│  ├─ founder_vision.md          # distilled from Screener.md §1–5
│  ├─ product_principles.md      # §33 principles
│  ├─ architecture.md            # this plan's D/E expanded as living doc
│  ├─ data_strategy.md           # §G/H expanded; provider matrix
│  ├─ roadmap.md                 # P0/P1/P2 with dates
│  ├─ decision_log.md            # every irreversible decision + why
│  ├─ BUILD_PLAN.md
│  └─ features/                  # one spec per feature (template in §32 of Screener.md)
│     ├─ company-page.md
│     ├─ opportunity-finder.md
│     ├─ scoring-engine.md
│     ├─ thesis-tracker.md
│     └─ ...
├─ backend/
│  ├─ app/
│  │  ├─ api/                    # FastAPI routers — HTTP only, no business logic
│  │  │  └─ v1/
│  │  ├─ core/                   # config, settings, logging, security, errors
│  │  ├─ domain/                 # market-agnostic domain models + value objects
│  │  ├─ services/               # application services (orchestration + tx boundaries)
│  │  ├─ providers/              # data provider abstraction
│  │  │  ├─ base.py              # Protocols: MarketData / Fundamental / News / CompanyData
│  │  │  ├─ registry.py          # (market, capability) -> ordered provider list
│  │  │  ├─ india/
│  │  │  │  ├─ upstox.py         # PRIMARY market data (candles/quotes/instruments)
│  │  │  │  ├─ nse_bhavcopy.py   # EOD spine + delivery% (auth-free fallback)
│  │  │  │  ├─ yfinance.py       # best-effort fundamentals/backfill (secondary)
│  │  │  │  ├─ rss_news.py       # RSS/GDELT news
│  │  │  │  └─ nse_actions.py    # corporate actions
│  │  │  └─ auth/                # Upstox OAuth/token manager
│  │  ├─ engines/
│  │  │  ├─ indicators/          # technical calcs (we compute these ourselves)
│  │  │  ├─ opportunity/         # screens (Layer 1) + attention ranking (Layer 2)
│  │  │  ├─ scoring/             # configurable, industry-aware scoring
│  │  │  ├─ thesis/              # thesis trigger evaluation (added feature)
│  │  │  └─ historical/          # event/recovery comparison (P2)
│  │  ├─ ai/                     # LLM layer: retrieval, grounding, prompts, citations
│  │  ├─ jobs/                   # scheduled ingestion / refresh / thesis-eval jobs
│  │  ├─ db/                     # models, session, alembic migrations
│  │  └─ main.py
│  ├─ tests/                     # unit (engines) + integration (providers, api)
│  ├─ pyproject.toml
│  └─ .env.example
├─ frontend/
│  ├─ app/                       # Next.js App Router (server components fetch data)
│  ├─ components/
│  │  ├─ ui/                     # shadcn primitives
│  │  ├─ charts/                 # PriceChart, Sparkline, ScoreBreakdown
│  │  └─ domain/                 # MetricPanel, NewsList, OpportunityTable, ThesisCard
│  ├─ lib/                       # typed api client, formatters (currency/number/date)
│  └─ package.json
├─ .github/workflows/ci.yml      # lint + typecheck + test
├─ docker-compose.yml            # local Postgres (+ optional Redis)
└─ README.md
```

**Dependency rule (enforced in review):** `api → services → engines | providers → db`. API never imports providers or DB models. Engines never do IO. This is what makes new features additive instead of invasive.

---

## B. Technology Decisions & Alternatives

| Layer | Choice | Why | Alternatives |
|---|---|---|---|
| Frontend | **Next.js (App Router) + TS** | Spec-directed; Vercel free; SSR = fast company pages, keys stay server-side | Remix, Vite/React |
| Styling | **Tailwind + shadcn/ui** | Serious/clean look fast; minimal custom CSS | MUI, Chakra |
| Charts | **lightweight-charts (OHLC) + Recharts (metrics)** | Finance-grade candles + simple metric panels | ECharts, visx |
| Backend | **FastAPI + Python 3.12** | Spec-directed; ideal for data/ML glue | Litestar, Django-Ninja |
| ORM | **SQLAlchemy 2.0 + Alembic** | Explicit, mature migrations | SQLModel, Prisma-py |
| DB | **PostgreSQL** — Supabase or Neon free tier | Spec-directed; Supabase also gives free Auth (helps P1) | local-only in dev |
| Cache/queue | **DB freshness first; Redis only when measured** | Budget ~0 | Redis (defer) |
| Jobs | **APScheduler in-process (MVP)** → Celery later | Zero extra infra | Celery+Redis, cron |
| Data validation | **Pydantic v2** | Request + provider-response validation | — |
| Auth (P1) | **JWT (fastapi-users) or Supabase Auth**, behind `AuthProvider` | Swappable | Clerk/Auth0 free |
| AI | **Provider-abstracted LLM client**, strict grounding | Anti-hallucination + swappable | — |
| HTTP client | **httpx (async) + tenacity retries** | Async ingestion, backoff | requests |
| Pkg mgmt | **uv (py) / pnpm (js)** | Fast, reproducible | poetry / npm |
| Testing | **pytest + vitest + Playwright (smoke)** | Layered coverage | — |

All irreversible picks logged in `docs/decision_log.md`.

---

## C. Database Architecture

PostgreSQL. Market-agnostic core so US/MF/ETF/Crypto slot in later. **Store only what reduces repeat API calls or powers analysis.** Every fact-bearing row carries `source` + `as_of`/`fetched_at` (provenance is mandatory — it powers "facts vs interpretation").

### Core entities

**Market-agnostic instrument layer**
- **`asset`** — `id, symbol, exchange, market ('IN'), asset_class ('EQUITY'), currency, isin, name, active`. India is a *value*, never a code branch.
- **`instrument_map`** — `asset_id, provider, provider_instrument_key`. Maps our asset to Upstox `instrument_key`, yfinance ticker, NSE symbol, etc. **Critical:** Upstox addresses instruments by its own key, not the plain symbol.
- **`company`** — `asset_id, sector, industry, industry_code, description, mgmt_notes`.
- **`industry`** — taxonomy + which score profile applies.

**Market data**
- **`price_ohlcv`** — `asset_id, date, o,h,l,c, volume, oi, adj_close, delivery_qty, delivery_pct, source`. **Full daily bar stored for all available history** (enables past comparison, volume philosophy, candlesticks — decision D-006). **Corporate-action adjusted.** PK `(asset_id, date)`; index on `date`.
- **`corporate_action`** — `asset_id, type (split/bonus/dividend/rights), ex_date, ratio/amount, source`. Drives adjustment.

**Fundamentals**
- **`financial_statement`** — `asset_id, period_type (FY/Q), period_end, statement_type, line_item, value, source, as_of, confidence`.
- **`financial_metric`** — derived ratios (ROE/ROCE/D-E/margins/growth) `period, value, source, as_of, confidence`.

**News & events**
- **`news_article`** — `id, asset_id?, url, source, published_at, title, summary, sentiment, event_type, relevance, dedup_hash`.
- `corporate_event` — earnings/board meeting/results calendar.

**Analysis outputs**
- **`opportunity`** — `asset_id, screen_id, as_of, rank, snapshot_json`.
- `score` — `asset_id, profile_id, as_of, value, coverage, confidence`.
- `score_component` — `score_id, component, raw_value, normalized_value, weight, contribution` + **input snapshot** → enables future backtesting.

**User layer (P1)**
- `user`, `portfolio`, `holding`, `watchlist`, `watchlist_item`.

**Added features**
- **`thesis`** — `id, user_id, asset_id, title, body, stance (bull/bear/neutral), conviction (1–5), created_at, status (active/invalidated/closed)`.
- **`thesis_trigger`** — `id, thesis_id, metric, operator, threshold, direction, description`. e.g. `debt_equity > 1.5`.
- **`thesis_event`** — `id, thesis_id, trigger_id, fired_at, observed_value, note`. Append-only log of when a thesis was challenged/confirmed.

**Ops / P2**
- **`provider_fetch_log`** — `provider, endpoint, asset_id, fetched_at, status, latency_ms, ttl` → caching + freshness + provider-health.
- `historical_event` (P2) — prior sharp falls + reason + recovery outcome.

**Design rules:** no table without a consumer; JSONB (`snapshot_json`) for flexible/rarely-queried blobs; indexes on `(asset_id, date/period)` hot paths; migrations reviewed in PR.

---

## D. Backend Architecture

One-directional layering:

```
FastAPI routers (api/v1)     ← HTTP, validation, auth, serialization ONLY
        ↓
Application services         ← orchestrate: cache → provider → engine → persist; own tx
        ↓
Engines           Providers  ← pure calc (no IO)  |  the ONLY place external IO happens
        ↓               ↓
              PostgreSQL / cache
```

- **Engines are pure** over data we already hold → deterministic, unit-testable, no network. (indicators, opportunity, scoring, thesis-eval)
- **Providers are the only IO boundary**, behind interfaces (§F). They return normalized domain objects, never raw JSON.
- **Services** own caching/freshness policy + DB transactions + orchestration.
- **AI** consumes engine/DB output; never computes financial numbers, never fetches raw external data.
- **Jobs** call services (not providers directly) so caching/freshness apply uniformly.

Error handling: providers raise typed `ProviderError`; services translate to domain results with `coverage/confidence`; API maps to HTTP with a consistent error envelope.

---

## E. Frontend Architecture

- Next.js App Router; **Server Components** fetch company/opportunity data → fast first paint, secrets never reach the browser.
- Thin typed API client in `lib/`. **No external provider calls from the browser — ever.**
- Component tiers: shadcn primitives → charts → domain components → pages.
- **Design tokens first** (muted palette, type scale, spacing) to hit Bloomberg/Linear/Notion feel and avoid casino/trading-app aesthetics.
- **Progressive disclosure** on the company page: 4–5 things that matter up front, expand for the rest (avoid information overload per §11/§24).
- **Price chart = candlesticks** from stored OHLCV, **corporate-action-adjusted**, with **ex-date markers** annotating splits/bonuses/dividends ("1:2 split", "1:1 bonus") so users see why the series steps; optional close-only line view for long-range zoom. *(Decisions D-005/D-007.)*
- Provenance affordance: every metric can reveal `source` + `as_of` on hover; low-confidence/missing data is visibly flagged, never hidden or faked.
- Desktop-first, responsive. Perf budget: company page interactive < ~2s on cached data.

---

## F. Data Provider Abstraction

Four capability interfaces; implementations registered per market with **ordered fallbacks**. If a source dies we write one class — never a rewrite.

```python
class MarketDataProvider(Protocol):
    def get_universe(index: str) -> list[AssetRef]: ...           # Nifty 500
    def get_ohlcv(asset, start, end, interval) -> list[Bar]: ...
    def get_quote(assets: list) -> dict[Asset, Quote]: ...        # batch
    def get_corporate_actions(asset) -> list[Action]: ...

class FundamentalDataProvider(Protocol):
    def get_statements(asset, period) -> Statements: ...
    def get_ratios(asset) -> Ratios: ...

class NewsProvider(Protocol):
    def get_news(target, since) -> list[Article]: ...

class CompanyDataProvider(Protocol):
    def get_profile(asset) -> CompanyProfile: ...
```

- **Registry:** `(market, capability) → [provider, fallback, …]`. e.g. `('IN', OHLCV) → [Upstox, NSEBhavcopy, yfinance]`.
- Providers normalize to domain objects; engines stay provider-agnostic.
- Every provider call is logged to `provider_fetch_log`.
- **Auth is provider-internal:** the Upstox provider owns its token lifecycle (§G) so the rest of the app is oblivious to it.

---

## G. Initial Indian Market Data Strategy (Upstox-first)

> 📎 **Full source registry with fallback chains lives in `API_Sources.md`** — every data need mapped to primary + fallback APIs, trust tier, and free-tier caveats. The matrix below is the summary.

**Provider responsibility matrix** — what comes from where, given Upstox as the preferred market-data source:

| Data need | Primary | Fallback / Secondary | Notes |
|---|---|---|---|
| Instruments master / keys | **Upstox instrument dump** | NSE symbol list | Populates `instrument_map` |
| Nifty 500 universe | **NSE index CSV** | derive from instruments | Constituents change; refresh monthly |
| EOD OHLCV | **Upstox historical (daily)** | **NSE Bhavcopy** | Upstox daily = **only 1yr lookback** |
| Deep daily history (multi-yr) | **NSE Bhavcopy accumulation** / Upstox weekly | — | Upstox daily capped at 1yr → store incrementally |
| Intraday / quotes / LTP | **Upstox** (quote batch + WebSocket) | — | Not needed for EOD MVP; available later |
| Open Interest | **Upstox** | — | Bonus field for derivatives context |
| **Delivery %** | **NSE Bhavcopy** | — | **Upstox does NOT provide this** |
| Corporate actions | NSE/BSE announcements | Upstox instrument metadata | Drives price adjustment |
| **Fundamentals** | yfinance (best-effort) / curated | XBRL (P2) | **Upstox does NOT provide this** — biggest gap |
| News | RSS (MC/ET/BS) + GDELT | Google News RSS | Free |
| Sentiment/event class | LLM or local model | — | Cache aggressively |

### Upstox specifics (verified against docs, to re-confirm at build time)
- **Historical candle** returns `[timestamp, O, H, L, C, Volume, Open Interest]`. Intervals & lookback: **1-min ≈ 1–6 months, 30-min ≈ 1 year, Daily = 1 year, Weekly/Monthly = 10 years.** One instrument per request.
- **Implication:** for indicators we only need ~1 year of daily (DMA-200 ≈ 200 trading days) → Upstox daily is sufficient for MVP. For the **P2 historical-event engine** (multi-year daily) we must **accumulate daily bars over time** and/or backfill via bhavcopy/weekly. Flagged in §U.
- **Auth:** Bearer token via OAuth login; **documented behavior is that the access token expires daily (~03:30 IST) and requires re-login.** This breaks naive unattended jobs.
  - **Design:** an `UpstoxTokenManager` isolates this. Strategy options (decision in §V): (a) automated OAuth+TOTP daily refresh, (b) semi-manual daily token paste via an admin endpoint, (c) treat Upstox as *best-effort enrichment* and let **auth-free NSE Bhavcopy be the guaranteed unattended EOD spine.** **Recommended: (c) as the safety net + (a) when feasible** — the app never breaks if the Upstox token lapses.
- **Rate limits + single-instrument history:** ingesting 500 daily candles = 500 calls → throttle with backoff, run off-peak, spread across the ingestion window.

### Principle
**EOD-first.** We are not a realtime terminal. Daily batch ingestion is sufficient, cheap, and simple. Upstox gives us a clean primary market-data feed and a path to intraday later; Bhavcopy guarantees the pipeline never depends on a live token.

---

## H. Free / Low-Cost Data-Source Feasibility Assessment

> ⚠️ Spec rule honored: **re-verify each at build time** (availability, rate limits, ToS/redistribution). Planning-time web verification was partial; treat as hypothesis.

| Need | Source | Feasibility | Caveat |
|---|---|---|---|
| Instruments / keys | Upstox dump | ✅ High | Map to `instrument_map` |
| Nifty 500 universe | NSE CSV | ✅ High | Format/header changes |
| EOD OHLCV + OI | Upstox daily | ✅ High | **1-yr daily lookback** |
| EOD spine (unattended) + delivery% | NSE Bhavcopy | ✅ High | EOD only; URL/format drift |
| Intraday/quotes/WebSocket | Upstox | ✅ (later) | Daily token; not in MVP |
| Corporate actions | NSE/BSE announcements | ⚠️ Medium | Parsing effort |
| **Fundamentals** | yfinance / XBRL | ❌ **Biggest gap** | Indian coverage spotty & unreliable; screener.in/Tickertape/Trendlyne have **no free API**, scraping breaks ToS |
| News | RSS + GDELT | ✅ High | Dedup + relevance work |
| Sentiment / event type | LLM | ✅ (compute) | Cost → cache by content hash |

**Fundamentals fallback plan (unchanged, still the crux):** MVP ships **partial fundamentals + explicit "unavailable / low-confidence" flags** (never fabricated). Consider a **curated Nifty 500 core-fields dataset** to guarantee a usable MVP. XBRL parsing is a P2 initiative. Keep a low-cost paid fundamentals API behind the same interface as a *later* option — not an MVP dependency.

---

## I. Caching Strategy

Every external read: **request → cache lookup → freshness check → serve if valid → refresh only if stale.**

- **TTL by type:** EOD prices valid until next trading session; fundamentals quarterly; news hourly; profile weekly; instruments master daily.
- **MVP cache = Postgres** (stored data + `provider_fetch_log`). No Redis until a measured need appears.
- **Batch + incremental:** one daily job for the whole universe; only changed rows updated.
- **Compute-don't-fetch:** all technical indicators derived locally from stored OHLCV.
- **Trading-calendar aware:** don't attempt refresh on market holidays; freshness respects last trading day.

---

## J. API Strategy

- REST under `/api/v1`, versioned from day one. Consistent envelope: `{ data, meta: { as_of, source, confidence } }`.
- Representative endpoints:
  - `GET /assets/search?q=`
  - `GET /companies/{symbol}` — aggregated company-page payload
  - `GET /companies/{symbol}/prices?range=&interval=`
  - `GET /companies/{symbol}/financials`
  - `GET /companies/{symbol}/technicals`
  - `GET /companies/{symbol}/news`
  - `GET /companies/{symbol}/score` — value + component breakdown
  - `GET /opportunities?screen=&universe=&period=`
  - `POST /screener/run` — combinable condition tree (P2)
  - `POST /ai/analyze` — grounded analysis (P1)
  - `POST /theses` / `GET /theses` / `GET /theses/{id}` — Thesis Tracker (P1)
  - `POST /admin/upstox/token` — daily token refresh (admin-only, if manual strategy)
- Rate-limit expensive endpoints (AI, screener, search).

---

## K. Opportunity Engine Architecture

Two layers, exactly as the vision describes:

- **Layer 1 — Screens (filters):** each screen is a small registered unit implementing `evaluate(universe, params) -> [Hit]`. Examples: `DownOverPeriod(5/10/15/30/60/90d)`, `BelowDMA(50/100/200)`, `UnusualVolume`, `ValuationCompression`, `ImprovingEarnings`, `DecliningDebt`, `PositiveCashFlow`, `RelativeStrengthVsSector`, `RelativeStrengthVsNifty`. **New screen = new class, zero core changes.**
- **Layer 2 — Attention ranking:** annotate Layer-1 hits with context (fundamental trend intact? news temporary vs structural? historical analog recovered? debt stable?) so "-22% but stable" outranks "-30% deteriorating."
- **Combinable conditions** (`fell >20% AND ROCE>15% AND debt declining AND CF positive`) expressed as an AND/OR tree over registered screens (advanced screener = P2).
- Runs entirely against **stored** data → fast, no live API storms.

---

## L. Scoring Engine Architecture

- Score = weighted aggregation of **components** (price, technical, fundamentals, valuation, participation, news, historical, management).
- **Weights are versioned configuration, never code constants.**
- **Missing-data-graceful:** each component returns `(raw, normalized, coverage, confidence)`; aggregator renormalizes over *available* components and reports overall coverage/confidence.
- **Peer/industry normalization:** components normalized to **percentile rank within industry** where sensible (raw ROCE → "85th percentile of its industry") — makes the score defensible.
- **Explainable:** persist per-component `contribution` → UI shows a waterfall/breakdown, not a bare number.
- **Snapshot inputs every run** (`score_component` + `snapshot_json`) → enables future backtesting/optimization with no data time machine.
- **Labeling enforced:** output is "research attractiveness / opportunity characteristics," never a return prediction — enforced in copy and AI prompts.

---

## M. Industry-Specific Scoring Design

- A **score profile** = `{industry_code → {component → weight, relevant_metrics}}`, stored as versioned DB rows.
- Seed profiles shipped: **Banking** (NIM, GNPA/NNPA, credit growth, CASA, capital adequacy, provisions), **IT** (revenue growth, EBIT margin, deal wins, attrition, client concentration, cash generation), **Manufacturing** (capacity utilization, order book, ROCE, debt, operating leverage, raw-material costs), plus a **Default** profile.
- Resolution: `industry → profile → weights`, fallback to Default if unmapped.
- Future adaptive/learned/backtested weights plug in **behind the same profile interface** — no engine rewrite.

---

## N. AI Architecture

Grounding is the whole point.

- **Retrieval-grounded:** the AI receives only structured, cited data we already hold (metrics, news, events). It does not free-browse or invent numbers.
- **Output contract:** every analysis returns structured sections — *What happened / Why / What changed / What didn't / Bull / Bear / Risks / Supporting evidence / Contradicting evidence / What to monitor / Confidence* — with **inline citations to the exact datapoint or article.**
- **Facts vs interpretation** separated structurally and visually.
- **Banned-phrase guard:** reject/rewrite "guaranteed," "risk-free," "will go up," etc. (§28).
- LLM client is provider-abstracted; responses cached by `(asset, data-fingerprint)` to bound cost.
- Deterministic financial math stays in engines; AI only narrates/reasons over engine output.
- MVP AI = **single-company analysis (P1)**; NL research assistant = P2.

---

## O. Authentication Approach

- **P0: no auth** — public read-only browsing (universe, company, opportunities). Ships faster, zero user-data liability.
- **P1:** JWT via `fastapi-users` (or Supabase Auth if we pick Supabase), behind an `AuthProvider` interface. Argon2/bcrypt hashing; short-lived access + refresh tokens.
- Portfolio / watchlist / thesis gated behind auth when introduced.
- **Note:** Upstox OAuth (§G) is a *data-provider* concern, entirely separate from *user* auth. Don't conflate them.

---

## P. Security Considerations

- Secrets in env only; `.env.example` committed, `.env` git-ignored. **No keys in frontend.**
- **All external provider calls server-side only**; Upstox token never leaves the backend.
- Pydantic validation on every endpoint; ORM parameterized queries (no string SQL).
- Rate-limit AI/screener/search/token endpoints; admin endpoints authn+authz gated.
- CORS locked to known origins; security headers; least-privilege DB user.
- Dependency scanning in CI; migrations reviewed.

---

## Q. MVP Scope

A **publicly usable, read-only research tool for the Nifty 500** in ~1 week:

- Seeded universe + search.
- Company page: header, price chart, performance, **locally-computed technicals**, best-effort fundamentals (**coverage-flagged**), news, basic Opportunity Score with breakdown.
- Opportunity Finder: core price/technical screens + attention ranking.
- Daily ingestion job (Upstox primary + Bhavcopy spine) feeding everything from stored data.

**Out of MVP:** auth, portfolio, watchlist, CSV import, thesis tracker, NL assistant, historical-event engine, advanced screener, alerts, adaptive scoring, intraday/WebSocket.

---

## R. P0 / P1 / P2 Feature Priorities

**P0 (MVP):** foundation • universe • search • company page • price history/chart • basic financials (flagged) • basic technicals • news • opportunity finder • basic opportunity score.

**P1:** authentication • portfolio • watchlist • Zerodha CSV import • AI single-company analysis • **Thesis Tracker (conviction + invalidation triggers)** • **provenance UI polish**.

**P2:** historical event/recovery engine • advanced combinable screener • full industry-specific scoring profiles • intelligent alerts (incl. thesis-trigger alerts) • NL research assistant • score backtesting/optimization • peer-percentile expansion • Upstox intraday/WebSocket.

> Added features (Thesis Tracker, provenance, score snapshotting, peer normalization, provider-health) are now embedded in the sections above. Snapshotting, provenance, corporate-action adjustment, and provider-health are built into P0 schema/engines because retrofitting them is expensive; the *user-facing* Thesis Tracker lands in P1.

---

## S. Exact Implementation Sequence

Each step = one committable, testable unit sized for Claude Pro limits: implement → test → fix → commit → next.

**P0**
1. Scaffold repo (git init, backend+frontend skeletons, docker-compose Postgres, CI).
2. DB layer: `asset/instrument_map/company/industry/price_ohlcv/corporate_action` + Alembic migration.
3. Provider abstraction interfaces + registry + `provider_fetch_log` + unit tests (no impls).
4. **Upstox provider**: `UpstoxTokenManager` + instruments dump → seed `asset`/`instrument_map`; daily historical candles.
5. **NSE Bhavcopy provider**: auth-free EOD spine + delivery% (fallback + delivery data).
6. Corporate-action ingestion + price adjustment (with tests — correctness-critical).
7. Indicator engine (DMA 20/50/100/200, RSI, MACD, volatility, drawdown, rel-strength/volume) — pure + unit-tested.
8. API: search + company page (prices + technicals).
9. Frontend: design tokens, layout, search, company page (price chart + technical panel + provenance affordance).
10. FundamentalDataProvider (best-effort) + financial panels **with coverage/confidence flags**.
11. NewsProvider (RSS/GDELT) + dedup + news panel.
12. Opportunity screens (Layer 1) + `/opportunities` + Finder UI.
13. Scoring engine (configurable, missing-data-graceful, peer-normalized) + breakdown UI + **input snapshotting**.
14. Attention ranking (Layer 2).
15. Deploy: Vercel (fe) + Render/Fly (be) + Supabase/Neon (db) + scheduled ingestion. **→ Public MVP.**

**P1 (each a spec in `docs/features/`)**
16. Auth. 17. Portfolio + Zerodha CSV import. 18. Watchlist. 19. AI single-company analysis (grounded + cited). 20. **Thesis Tracker** (see §X).

**P2**
21. Historical event/recovery engine (needs deep-history strategy — see §U). 22. Advanced combinable screener. 23. Full industry scoring profiles. 24. Intelligent alerts (incl. thesis triggers). 25. NL research assistant. 26. Score backtesting. 27. Upstox intraday/WebSocket.

---

## T. Estimated Complexity Per Feature

| Feature | Complexity | Note |
|---|---|---|
| Scaffold | S | |
| DB + migrations | S–M | |
| Provider interfaces | S | |
| **Upstox provider + token manager** | **M–L** | daily-token lifecycle is the tricky part |
| NSE Bhavcopy ingestion | M | format handling |
| Corporate-action adjustment | M | correctness-critical, well-tested |
| Indicator engine | M | pure math, testable |
| Search + company API | S–M | |
| Company page UI + charts | M | |
| Fundamentals provider | **L** | **data availability is the risk, not code** |
| News (fetch+dedup+classify) | M–L | |
| Opportunity screens + finder | M | |
| Scoring engine + breakdown + peer norm | M–L | |
| Attention ranking | M | depends on fundamentals/news quality |
| Deploy/ops | M | free-tier limits, scheduled jobs, token refresh |
| Auth (P1) | M | |
| Portfolio + Zerodha CSV (P1) | M | format variance |
| AI analysis + grounding (P1) | **L** | citation/grounding correctness |
| **Thesis Tracker (P1)** | **M** | trigger DSL + eval job + alerts |
| Historical event engine (P2) | **L** | needs multi-year daily history |

---

## U. Risks / Blockers

1. **Fundamentals data (highest risk).** No reliable free API with good Indian coverage; obvious sources violate ToS. Upstox does **not** help here. → MVP partial + flagged; consider curated seed; XBRL later.
2. **Upstox daily token expiry.** Unattended jobs break when the token lapses. → `UpstoxTokenManager` + **Bhavcopy as the auth-free guaranteed spine**; automate OAuth refresh if feasible.
3. **Upstox daily-history 1-year cap + single-instrument requests.** Deep history for the P2 event engine isn't available on demand. → **accumulate daily bars from day 1**, backfill via bhavcopy/weekly; throttle 500-call ingestion.
4. **Bhavcopy/NSE format drift & scrape-hostility.** → resilient parsers + monitoring via `provider_fetch_log`.
5. **Free-tier hosting limits** (cold starts, job-time caps, DB row/connection limits). → EOD batch, lean storage.
6. **Corporate-action correctness.** Wrong adjustment silently corrupts every indicator/return. → dedicated tests.
7. **AI hallucination / over-claiming.** → strict grounding, citations, facts/interpretation split, banned-phrase guard.
8. **News dedup/relevance quality.** → hashing + relevance scoring; accept modest recall in MVP.
9. **One-week timeline vs data plumbing reality.** Ingestion/quality is the long pole, not UI.
10. **Regulatory (SEBI).** Research-analyst rules are stricter than a generic disclaimer. → deliberate "education/research, not advice" positioning + disclaimer; log the decision.

---

## V. Questions That MUST Be Resolved Before Coding

1. **Fundamentals for MVP:** partial-flagged / curated Nifty 500 dataset / defer to P1? *(biggest decision — Upstox does not solve this.)*
2. **Upstox token strategy:** automated OAuth+TOTP refresh vs semi-manual daily paste vs Upstox-as-enrichment-only with Bhavcopy spine? *(Recommend: Bhavcopy spine + automate Upstox when feasible.)*
3. **DB/host:** Supabase (Postgres + free Auth, speeds P1) vs Neon (pure Postgres)?
4. **Backend host:** Render vs Fly.io vs Railway (free-tier + job scheduling tradeoffs).
5. **AI provider + hard monthly cost cap.**
6. **SEBI positioning stance + disclaimer copy** before public launch.
7. **"~1 week" definition:** include fundamentals plumbing, or is prices+technicals+news+opportunity acceptable for v1 (fundamentals following)?
8. **Confirm EOD-only** for MVP (strongly recommended; intraday via Upstox is P2).
9. **Deep-history backfill:** start accumulating Upstox daily bars now, or source a one-time multi-year backfill for the P2 event engine?

---

## W. Definition of Done — MVP

- [ ] Public URL loads a clean, fast company page for any Nifty 500 stock.
- [ ] Price chart renders **corporate-action-adjusted candlesticks** (Upstox primary, Bhavcopy fallback) with **visible split/bonus/dividend markers on ex-dates**; core technicals computed locally and correct (unit-tested).
- [ ] Fundamentals shown where available, **explicitly flagged** where not — **no fabricated numbers.**
- [ ] Relevant, deduplicated news per company.
- [ ] Opportunity Finder returns ranked candidates for standard screens over the Nifty 500.
- [ ] Opportunity Score displays with a **per-component breakdown**; missing data graceful; labeled "research characteristics," not a return prediction.
- [ ] Daily ingestion runs unattended; **pipeline does not break if the Upstox token lapses** (Bhavcopy spine); pages served from stored data (no per-refresh API storms).
- [ ] Every fact-bearing datapoint carries `source` + `as_of`; provenance visible in UI.
- [ ] No secrets in repo or frontend; sensitive/admin endpoints rate-limited + gated.
- [ ] CI green (lint + tests); README explains local setup incl. Upstox token bootstrap.
- [ ] Disclaimer / positioning copy present.

---

## X. Feature Mini-Specs

> Full specs live in `docs/features/`. These summarize the features added at the user's request. Template per Screener.md §32.

### X.1 Thesis Tracker / Conviction Journal *(P1 — flagship added feature)*

- **Purpose:** Let an investor record an investment thesis and the *conditions that would invalidate it*, then have the platform actively watch those conditions — the concrete expression of the vision's "build **or challenge** conviction."
- **User problem:** Investors form theses ("Ola's battery arm is the real long-term value") but forget them, and rarely define upfront what would prove them *wrong*. Confirmation bias goes unchecked.
- **Inputs:** thesis title/body, stance (bull/bear/neutral), conviction (1–5), one or more **invalidation triggers** (`metric operator threshold`, e.g. `debt_equity > 1.5`, `revenue_growth < 5% for 2 quarters`, `price < 200DMA`).
- **Outputs:** a thesis dashboard; per-thesis status (active / **challenged** / invalidated); an append-only event log of when each trigger fired with the observed value; optional alert.
- **Business logic:** a scheduled `thesis-eval` job runs after each daily ingestion; for every active trigger it evaluates the operator against the latest stored metric; on fire it writes a `thesis_event` and (P2) emits an alert. No trading action, no recommendation — it *surfaces evidence that challenges the user's own stated view.*
- **Data:** `thesis`, `thesis_trigger`, `thesis_event`; reads `financial_metric` / `price_ohlcv` / indicators. Reuses the same metric registry the screener/scoring use.
- **API:** `POST /theses`, `GET /theses`, `GET /theses/{id}`, `PUT /theses/{id}`, `DELETE`.
- **UI:** ThesisCard (stance, conviction, triggers, status) + timeline of trigger events; "what would invalidate this?" prompt at creation.
- **Edge cases:** metric unavailable (trigger = "cannot evaluate," never silently false); trigger references a metric with low confidence → flag; thesis on a delisted/inactive asset.
- **Acceptance:** user creates a thesis with ≥1 trigger; after ingestion, a trigger whose condition is met produces a visible `thesis_event`; no fabricated evaluations when data is missing.

### X.2 Provenance & Grounded Citations *(baked into P0 schema + AI contract)*
- Every fact-bearing datapoint carries `source` + `as_of`, surfaced on hover; AI answers cite the exact datapoint/article. Enforces "facts vs interpretation."

### X.3 Score-Input Snapshotting *(baked into P0 scoring engine)*
- Persist component inputs + weights on every score computation → future backtesting/optimization without reconstructing history.

### X.4 Peer / Industry Percentile Normalization *(P0 where feasible, expanded P2)*
- Normalize metrics to percentile rank within industry so raw numbers become insight.

### X.5 Provider-Health Monitoring *(baked into P0 via `provider_fetch_log`)*
- Track per-provider success/latency/staleness → early warning when a free source (Upstox token, Bhavcopy format) breaks.

---

*End of build plan (v2). Awaiting review/approval before any implementation. Features will be built one-at-a-time with docs as the source of truth.*
