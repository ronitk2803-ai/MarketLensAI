# Architecture — `mlai`

> Living architecture doc. Expands `Build_plan.md` §D/E/F. Read alongside it. Codename `mlai`; market-agnostic core.

## Guiding constraints
- **Modular & additive:** a new feature is a new module behind existing interfaces, never a rewrite.
- **Market-agnostic domain:** India is a *data value*, never a code branch — enables US/MF/ETF/crypto later.
- **Provider-agnostic:** all external data behind swappable interfaces.
- **Separation of concerns:** data ingestion ≠ analysis engines ≠ AI ≠ UI.

## Layered overview
```
┌─────────────────────────────────────────────┐
│ Next.js (App Router, Server Components)       │  UI only; no external calls
└───────────────┬───────────────────────────────┘
                │ HTTPS  /api/v1
┌───────────────▼───────────────────────────────┐
│ FastAPI routers                                │  HTTP, validation, auth, serialization
└───────────────┬───────────────────────────────┘
┌───────────────▼───────────────────────────────┐
│ Application Services                           │  orchestration, tx, cache/freshness policy
└───────┬───────────────────────────┬────────────┘
        │                           │
┌───────▼─────────┐        ┌────────▼───────────┐
│ Engines (pure)  │        │ Providers (all IO) │
│ indicators      │        │ Upstox / Bhavcopy  │
│ opportunity     │        │ yfinance / RSS ... │
│ scoring         │        │ (behind interfaces)│
│ thesis          │        └────────┬───────────┘
│ historical (P2) │                 │
└───────┬─────────┘                 │
        │                           │
        └───────────┬───────────────┘
             ┌───────▼────────┐
             │ PostgreSQL /   │
             │ cache          │
             └────────────────┘
```
**Dependency rule (enforced in review):** `api → services → engines | providers → db`. API never imports providers or DB models; engines never do IO.

## Modules
- **`domain/`** — market-agnostic models & value objects (Asset, Bar, Ratios, Article…). No India specifics.
- **`providers/`** — the *only* place external IO happens. Four capability interfaces (MarketData, Fundamental, News, CompanyData) + a `registry` mapping `(market, capability) → [primary, fallback, …]`. Each provider owns its own auth (e.g. Upstox daily token). See `Build_plan.md` §F and `API_Sources.md`.
- **`engines/`** — pure, deterministic, unit-testable calculations over data we already hold:
  - `indicators/` — DMAs, RSI, MACD, volatility, drawdown, relative strength/volume (computed on **adjusted** series).
  - `opportunity/` — Layer 1 screens (composable, registered) + Layer 2 attention ranking.
  - `scoring/` — configurable, industry-aware, missing-data-graceful; snapshots inputs for future backtesting.
  - `thesis/` — evaluates user-defined invalidation triggers.
  - `historical/` — event/recovery comparison (P2).
- **`ai/`** — retrieval-grounded LLM layer; consumes engine/DB output, emits structured + cited analysis; never fetches raw data or computes financial math.
- **`services/`** — orchestrate cache → provider → engine → persist; own transactions and freshness rules.
- **`jobs/`** — scheduled ingestion / refresh / thesis-eval (APScheduler in MVP → Celery later). Jobs call services, not providers directly.

## Data flow (typical request)
1. Client requests a company page.
2. Service checks cache/freshness → serves stored data if valid.
3. If stale, provider (with fallbacks) fetches; result normalized to domain objects and persisted with `source + as_of`.
4. Engines compute indicators/score from stored data.
5. AI (if requested) narrates over the structured result with citations.
6. Response returned with `meta: { as_of, source, confidence }`.

## Ingestion flow (daily)
Universe refresh (monthly) → prices (Upstox primary / Bhavcopy spine) → corporate actions → **adjustment** → derived metrics/indicators → news fetch/dedup/classify → opportunity screens + scores (with input snapshots) → thesis-trigger evaluation. Auth-free Bhavcopy ensures the pipeline survives an Upstox token lapse.

## Correctness mechanisms
- Two-source **reconciliation** for prices & corporate actions; divergence → flag + prefer official.
- **Corporate-action adjustment** applied before indicators & charts (a split must not look like a crash).
- **Provenance** (`source + as_of + confidence`) on every fact; missing = flagged, never fabricated.
- **provider_fetch_log** powers caching, freshness, and provider-health monitoring.

## Frontend
Server Components fetch data (keys stay server-side); thin typed API client; shadcn primitives → charts → domain components → pages. Price chart = adjusted candlesticks with split/bonus markers. Progressive disclosure; muted, serious aesthetic (Bloomberg/Linear/Notion); desktop-first, responsive.

## Future expansion
New asset classes/markets = new provider implementations + new score profiles behind existing interfaces. Core domain, engines, and API contracts stay stable.

*See also: [`data_strategy.md`](data_strategy.md), [`../Build_plan.md`](../Build_plan.md), [`../API_Sources.md`](../API_Sources.md).*
