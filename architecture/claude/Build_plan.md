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

> **Status legend:** ✅ done · ⚠️ code done, blocked operationally · ❌ not started.
> Last updated 2026-08-26 (commit `88438e5`). Live inventory in `SUMMARISER.md` §4.

**P0 — complete**
1. ✅ Scaffold repo (git init, backend+frontend skeletons, docker-compose Postgres, CI).
2. ✅ DB layer: `asset/instrument_map/company/industry/price_ohlcv/corporate_action` + Alembic migration.
3. ✅ Provider abstraction interfaces + registry + `provider_fetch_log` + unit tests (no impls).
4. ✅ **Upstox provider**: `UpstoxTokenManager` + instruments dump → seed `asset`/`instrument_map`; daily historical candles. *(Token refresh stays semi-manual by design — §U.2.)*
5. ✅ **NSE Bhavcopy provider**: auth-free EOD spine + delivery% (fallback + delivery data).
6. ✅ Corporate-action ingestion + price adjustment (with tests — correctness-critical). *(Splits and bonuses only; the source feed misses bonuses and demergers — new risk §U.11.)*
7. ✅ Indicator engine (DMA 20/50/100/200, RSI, MACD, volatility, drawdown, rel-strength/volume) — pure + unit-tested.
8. ✅ API: search + company page (prices + technicals).
9. ✅ Frontend: design tokens, layout, search, company page (price chart + technical panel + provenance affordance).
10. ✅ FundamentalDataProvider (best-effort) + financial panels **with coverage/confidence flags**.
11. ✅ NewsProvider (RSS) + dedup + news panel. *(GDELT not wired; `event_type` is unpopulated — §U.8.)*
12. ✅ Opportunity screens (Layer 1) + `/opportunities` + Finder UI — 10 registered screens.
13. ✅ Scoring engine (configurable, missing-data-graceful) + breakdown UI + **input snapshotting**. *(Peer normalization is still outstanding — §X.4.)*
14. ✅ Attention ranking (Layer 2).
15. ⚠️ Deploy: Vercel (fe) + Render/Fly (be) + Supabase/Neon (db) + scheduled ingestion. **Runbook written (`Deployment.md`) and the full container stack proven locally; not yet executed against a public host.** No public URL exists. Checklist in `SUMMARISER.md` §8.1.

**P1 — complete**
16. ✅ Auth (JWT + refresh tokens, httpOnly cookies). **Extended beyond the original scope 2026-08-27:** email verification by 6-digit code, password reset by code, and Google sign-in — plus a verified-email gate on every endpoint that saves user data. See §X.7.
17. ✅ Portfolio + Zerodha CSV import — **extended beyond spec to multi-broker consolidation** (Zerodha + Upstox in one view, uniqueness `(user, asset, broker)`).
18. ✅ Watchlist.
19. ⚠️ AI single-company analysis (grounded + cited) — code complete and hardened; **blocked at runtime by a restricted Gemini key** (§U.12).
20. ✅ **Thesis Tracker** (see §X.1).
— ✅ Provenance UI polish.

**P2 — 4 of 7 done**
21. ✅ Historical event/recovery engine — see §X.6. *(§U.3's deep-history blocker is now resolved.)*
22. ✅ Advanced combinable screener — full AND/OR condition tree over a 28-metric registry.
23. ✅ Full industry scoring profiles — 2 profiles seeded (`default`, `financials`); others deliberately refused on measured evidence, see `app/engines/scoring/registry.py`.
24. ✅ Intelligent alerts (incl. thesis triggers).
25. ❌ NL research assistant — **blocked** on the same Gemini key (§U.12). Design and tool surface already exist.
26. ❌ Score backtesting.
27. ❌ Upstox intraday/WebSocket — needs API access.
— ❌ Peer-percentile normalization (§X.4).

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
| Historical event engine (P2) | **L** | ✅ built 2026-08-26; the multi-year history prerequisite is now satisfied (§U.3) |

---

## U. Risks / Blockers

1. **Fundamentals data (highest risk).** No reliable free API with good Indian coverage; obvious sources violate ToS. Upstox does **not** help here. → MVP partial + flagged; consider curated seed; XBRL later.
2. **Upstox daily token expiry.** Unattended jobs break when the token lapses. → `UpstoxTokenManager` + **Bhavcopy as the auth-free guaranteed spine**; automate OAuth refresh if feasible.
3. ~~**Upstox daily-history 1-year cap + single-instrument requests.**~~ **RESOLVED 2026-08-26.** The mitigation worked: `app.jobs.backfill_history` (Bhavcopy, committed monthly chunks) plus daily accumulation now holds **2021-08-25 → 2026-08-26 for all 500 active equities, averaging 1,078 bars each (984,796 rows)**. Step 21 was built on this and needs no on-demand deep fetch — `get_price_history` clamps any live refetch to 10 days regardless (`MAX_ON_DEMAND_FETCH_DAYS`).
4. **Bhavcopy/NSE format drift & scrape-hostility.** → resilient parsers + monitoring via `provider_fetch_log`.
5. **Free-tier hosting limits** (cold starts, job-time caps, DB row/connection limits). → EOD batch, lean storage.
6. **Corporate-action correctness.** Wrong adjustment silently corrupts every indicator/return. → dedicated tests.
7. **AI hallucination / over-claiming.** → strict grounding, citations, facts/interpretation split, banned-phrase guard.
8. **News dedup/relevance quality.** → hashing + relevance scoring; accept modest recall in MVP.
9. **One-week timeline vs data plumbing reality.** Ingestion/quality is the long pole, not UI.
10. **Regulatory (SEBI).** Research-analyst rules are stricter than a generic disclaimer. → deliberate "education/research, not advice" positioning + disclaimer; log the decision. *(Disclaimer copy is live in the UI; the formal positioning sign-off in §V.6 is still open.)*

11. **Corporate-action feed is incomplete — NEW, 2026-08-26, and the highest-impact live data bug.** The adjustment engine is correct, but `yfinance_actions` **misses bonus issues and demergers entirely**, so a mechanical price drop is carried through as a real fall. Measured: BAJFINANCE −79.9% (2025-06-16, 4:1 bonus absent), ABFRL −66.6% (demerger, no non-dividend action on file), VEDL −64.9% (demerger), 360ONE −50.3% (raw 1773.30 → 441.05, a 4× move with only a 2× split recorded), BAJAJFINSV −47.9%, SIEMENS −42.9%. Of 1,306 detected falls, 32 (2.5%) contain a session ≤ −20%. This corrupts **every** price-derived number for those names in those windows — DMAs, RSI, volatility, drawdown, the `down_*` screens, `technical_setup`, and the chart. → Step 21 exposes the tell (`worst_session_pct`) rather than suppressing it, which is how this was found. **Real fix needs a source that reports bonuses and demergers (NSE's own corporate-actions endpoint).** Note §6 was about *wrong* adjustment; this is about *missing input*, and the tests for §6 cannot catch it.

12. **AI provider key restricted — NEW, blocks steps 19 (runtime) and 25.** The Gemini key lists models fine (200 in ~0.6 s) but `generateContent` hangs or returns an empty-bodied 404, identically from host and container, with Google's own server headers. A Cloud-console API-key restriction, not a code/network/model problem. → Failure path hardened (bounded 45 s budget, `provider_fetch_log` recording, 10-minute negative cache, auth gate, real error text surfaced). Console fix documented in `SUMMARISER.md` §8.2.

13. **No general rate limiter — NEW.** The auth gate is still the only bound on `POST /screener/run`. Partially mitigated since: `POST /ai-summary` now requires a *verified* account, and the code endpoints carry per-user throttles (60s spacing, 10/hour, 5 guesses per code, each committed before the error is raised so `get_db`'s rollback can't erase them). None of that is a general-purpose limiter. Must be closed before a public deploy.

14. **Resend testing mode — NEW, and it fails in the direction that hides it.** Until a domain is verified at resend.com/domains, the default `onboarding@resend.dev` sender delivers only to the Resend account owner's own address and 403s for everyone else — so verification and password reset work perfectly for whoever is testing and fail for every real user. → The provider translates that 403 into a message naming the fix; `SUMMARISER.md` §8.2 states it as a prerequisite for public signup.

---

## V. Questions That MUST Be Resolved Before Coding

*Answers recorded as they were settled. Updated 2026-08-26.*

1. ✅ **Fundamentals for MVP:** **partial + explicitly flagged.** One provider (yfinance), always rendered at low confidence, missing fields omitted rather than estimated. Remains the project's biggest data weakness (§U.1); XBRL is the real fix.
2. ✅ **Upstox token strategy:** **Bhavcopy spine + semi-manual Upstox re-auth.** `UpstoxTokenManager` is in-memory and never stores password/PIN/TOTP. Two standing consequences: the token dies daily ~03:30 IST, **and every backend restart or redeploy clears it**. Automating it means a DB-backed token store — deliberately out of scope.
3. ⬜ **DB/host:** still open. Either works; see `Deployment.md` §1 for the pooled-vs-direct connection-string distinction that matters on Supabase.
4. ⬜ **Backend host:** still open. Both Render and Fly build `backend/Dockerfile` unchanged.
5. ✅ **AI provider + cost cap:** **Gemini free tier**, with the cap enforced structurally rather than by budget alarm — generation is click-triggered only (never a page load or a schedule), and a shared `source_hash` cache means one generation per company per "the underlying data actually changed". Cost is ₹0 by construction. *(The key itself is currently restricted — §U.12.)*
6. ⬜ **SEBI positioning stance:** disclaimer copy is live in the UI footer and `product_principles.md` fixes the approved/banned language, but the formal research-analyst positioning has **not** been signed off. Must close before a public launch.
7. ✅ **"~1 week" definition:** moot — fundamentals plumbing shipped inside P0 (step 10) rather than following it.
8. ✅ **Confirm EOD-only for MVP:** yes. Live-ish quotes come from `yfinance_quotes` on the company page and market overview; everything analytical is end-of-day. Intraday/WebSocket remains step 27.
9. ✅ **Deep-history backfill:** **accumulate + Bhavcopy backfill**, and it worked — 5 years × 500 companies, 984,796 bars. See §U.3.

---

## W. Definition of Done — MVP

*Checked 2026-08-26. Everything is met **except the public URL** — the stack
is verified end-to-end on `localhost:3100` against the real 500-company
database, but has never been hosted.*

- [ ] **Public URL** loads a clean, fast company page for any Nifty 500 stock. — **the one outstanding item.** Locally: ✅. Hosting checklist in `SUMMARISER.md` §8.1.
- [x] Price chart renders **corporate-action-adjusted candlesticks** (Upstox primary, Bhavcopy fallback) with **visible split/bonus/dividend markers on ex-dates**; core technicals computed locally and correct (unit-tested). ⚠️ *Adjustment is correct but its input feed is incomplete — §U.11.*
- [x] Fundamentals shown where available, **explicitly flagged** where not — **no fabricated numbers.**
- [x] Relevant, deduplicated news per company.
- [x] Opportunity Finder returns ranked candidates for standard screens over the Nifty 500.
- [x] Opportunity Score displays with a **per-component breakdown**; missing data graceful; labeled "research attractiveness," not a return prediction.
- [x] Daily ingestion runs unattended (APScheduler, 20:00 IST, 7 days a week); **pipeline does not break if the Upstox token lapses** (Bhavcopy spine); pages served from stored data.
- [x] Every fact-bearing datapoint carries `source` + `as_of`; provenance visible in UI via `ProvenanceBadge`.
- [~] No secrets in repo or frontend; admin endpoints gated. ⚠️ **Gated but NOT rate-limited — no rate limiter exists anywhere (§U.13).** Close before going public.
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
- *Live lesson (2026-08-26): the one provider that never wrote to this table — the LLM — is the one whose total failure went unnoticed for days. `record_fetch` is now wired into the AI path, and the error row is `commit()`ed rather than flushed, because the exception that follows it reaches `get_db`, which rolls the request back.*

### X.6 Historical Fall / Recovery Engine *(P2 step 21 — written after the build, 2026-08-26)*
- **Purpose:** answer `founder_vision.md`'s "has something similar happened before, and what happened after?" for a company against its own past. `Screener.md` §10 calls it "an important differentiator" and §10:477-479 constrains it: *"Do NOT present historical recovery as a prediction. It is context only."*
- **User problem:** a stock is down 40% and the reader has no way to tell whether this company has been here before, how long it took to come back, or whether it ever did.
- **Inputs:** the company's full stored corporate-action-adjusted close series. No `range` parameter — the window belongs to the engine, not the reader.
- **Outputs:** the current open fall (if any) with peak/trough/depth/duration/volatility/worst-session, plus up to 5 comparable past falls each with its recovery date and duration; `past_count`, `excluded_left_censored`, and an explicit `dimensions_compared` / `dimensions_unavailable` split.
- **Business logic:** an *event* is an underwater episode — walk closes keeping a running peak; open on the first close **strictly below** it, close on the first close **at or above** it, trough = lowest close inside (first of ties). Keep episodes ≤ −20% (the conventional bear-market line, matching `down_90d`). At most one episode is open and it is necessarily the last. Comparables rank by `abs(past.decline_pct − current.decline_pct)` in percentage **points**.
- **Three decisions that follow from "context, never a prediction":**
  1. **No blended similarity score.** Only 3 of the spec's 7 dimensions are computable; a composite would overstate that, its weights would be unversioned code constants (which §L forbids), and a single "87% similar" is exactly the artifact that gets read as *this is the analog, so expect the analog's outcome*.
  2. **No aggregate across episodes** — no median recovery time. A marginal new high can legitimately split one long fall into two: harmless for a dated list, wrong for a mean.
  3. **No Python symbol named "event"** — `thesis_event` already owns that word. Package `engines/historical/`, types `Episode`/`Comparable`, service `historical_episodes.py`. The URL keeps §C's user-facing word.
- **Data:** **no new table.** Deliberately recomputed per request: `recovered`/`recovery_date` change as bars arrive, and a past fall's magnitude changes *retroactively* when a missing split is discovered and the series is re-adjusted — a cached row would disagree with the chart above it on the same page. Reads all stored history (not a rolling window, which would make the reported past mutate daily); one index range scan on `price_ohlcv`'s `(asset_id, date)` PK, ~33 ms warm.
- **API:** `GET /companies/{symbol}/historical-events`, standard provenance envelope, `source = price_source`, `confidence = "low"` when there is no data or the current fall is left-censored.
- **UI:** `HistoricalEventsPanel` between Technicals and the AI summary. Current-fall stat strip, comparables table, a data-quality strip, and a footnote carrying three non-negotiable clauses: "not a forecast"; "history begins X, not its listing date"; "magnitude, duration and volatility only — not the reasons".
- **Edge cases:** left-censored falls (peak = first bar) are flagged, excluded from comparables, and counted; non-positive closes skipped; ETFs return empty (our actions source doesn't track unit consolidations); an ongoing fall reports `decline_pct` (peak→trough) *and* `current_drawdown_pct` (peak→latest) separately, with `trough_to_recovery_*` as `None` rather than "days so far"; `trough_is_latest_bar` flags a stock still making new lows. `worst_session_pct` is the tell for an unadjusted corporate action and is surfaced, not suppressed — which is how §U.11 was discovered.
- **Acceptance:** ADANIENT reports −71.3% over 69 days from its 2022-12-20 peak, unrecovered; TCS shows its 2022 −25.8% fall recovering after 501 days alongside the current one; a stock near its high shows `current: null` with past falls still listed. All verified live.

### X.7 Email Verification, Password Reset, Google Sign-In *(P1 auth extension, 2026-08-27)*
- **Purpose:** prove an address is real, provide a way back into a forgotten account, and offer a sign-in that needs no new password.
- **User problem:** a typo at signup produced an unrecoverable account we could never reach; a forgotten password had no recovery but a DB edit.
- **Business logic:** one `auth_code` table serves both code flows, distinguished by a `purpose` string. Codes are 6 digits, live 10 minutes, allow 5 guesses, and are spaced 60s apart with 10/hour. `code_hash` is HMAC-SHA256 **keyed on the app secret** — not the bare SHA-256 `RefreshToken` uses, because 20 bits of entropy behind a plain digest is reversed from a stolen DB instantly, and not Argon2, which would only slow that search while putting a 64 MiB allocation on an unauthenticated endpoint.
- **Two orderings that are load-bearing:** the wrong-guess counter is `commit()`ed *before* the 400 is raised, or `get_db`'s rollback erases it and the attempt limit does not exist; and a code whose email fails to send is marked *consumed* rather than rolled back, because the row is simultaneously the credential and the throttle record.
- **Gate:** `get_current_verified_user` returns **403** (session valid, account not yet permitted) on the 10 endpoints that save user data. Tokens carry only `sub`/`exp`, so verification is read from the row per request — an old token cannot bypass it, and verifying needs no re-login. Verified live.
- **Anti-enumeration:** `/password-reset/request` is always 200 (never 429 — that status would itself say the address is registered), and every confirm failure returns one byte-identical 400. The residual timing channel is documented rather than padded, because `POST /register` still answers 409 for a taken address and leaks the same fact outright.
- **Google linking** branches on the **existing** account's verification state. An unverified local account being linked has its password nulled, its sessions revoked and its codes consumed — federated account pre-hijacking (USENIX 2022): registration proves nothing, so an attacker can register a victim's address, hold a 30-day token, and inherit the account when the real owner signs in with Google.
- **Edge cases:** `email_verified` is checked with `is True` (the legacy userinfo endpoint named the field differently, and a missing key yields `None`); `?error=access_denied` from a cancelled consent screen is an ordinary outcome; a missing OAuth state cookie is a hard failure, not a skipped check.
- **Acceptance:** verified live on the container stack — new account unverified, gated write 403 with the copy shown in the UI, banner appears and clears, and **the same access token minted before verification works for a gated write afterwards**.

---

*Build plan v2, kept current with the build. Status markers in §S; risks and
resolutions in §U; live inventory and handover in `SUMMARISER.md`.*
