# SUMMARISER — Project Status & Handover (`mlai` / MarketLens AI)

> **Read this first.** What we're building, what is *actually built*, what is
> pending, and how to get it running on your machine. Codename `mlai`; the
> product name in the UI is **MarketLens AI**. Nothing is hard-coded to a brand.
>
> **Status as of 2026-08-26:** P0 and P1 complete. P2 is 4 of 7 steps done.
> The app runs end-to-end in containers on a developer machine against a live
> 500-company database with 5 years of prices. **It is not deployed to a
> public server yet** — see §8.

---

## 1. The one-liner

An **AI-powered investment research platform** for Indian equities (Nifty 500)
that helps investors **discover opportunities and build *or challenge* their
conviction**, moving from data → information → context → insight → opportunity.

It is **not** a buy/sell tipping service and **not** just another screener.

## 2. Core philosophy (non-negotiable — every reviewer enforces this)

- **Explain, don't recommend.** Never "BUY/SELL/HOLD". Present what happened,
  why, what changed, bull/bear cases, risks, and what to monitor.
- **Missing, never fabricated.** Every engine returns `None` where data is
  absent rather than a guessed number. Scores renormalize over what exists and
  report coverage. This is the single most-repeated invariant in the codebase.
- **Evidence over opinion.** Every fact-bearing datapoint carries `source` +
  `as_of` + `confidence`, and the UI shows it.
- **Research/education, not regulated advice.** No "guaranteed" / "risk-free" /
  "will go up" language anywhere.

## 3. Architecture as built

```
Next.js 16 App Router (frontend)
   │  Server Components call lib/api.ts directly
   │  app/api/* Route Handlers exist ONLY to bridge Client Components (BFF)
   ▼
FastAPI (backend)  —  api → services → engines | providers → db
                          │              │           │
                          │              │           └─ all external IO
                          │              └─ pure, no network, unit-tested
                          └─ orchestration: cache → provider → engine → persist
   ▼
PostgreSQL 16 (23 tables)
```

**Enforced dependency rule:** `api → services → engines | providers → db`.
The API never imports providers or DB models directly; engines never do IO.

**Two response shapes, deliberately:**
- Market data → provenance envelope `{data, meta: {as_of, source, confidence}}`,
  fetched via `apiFetch`.
- User-authored content (auth, theses, portfolio, alerts) → **bare JSON**, via
  `apiFetchRaw`. It has no provenance because the user *is* the source.

**Ownership scoping:** every user-owned row is fetched with
`filter_by(id=X, user_id=Y).one_or_none()` and a miss returns **404, never
403** — so "wrong id" and "someone else's row" are indistinguishable.

## 4. What is built — complete inventory

### 4.1 Build_plan §S sequence status

| # | Step | Status |
|---|---|---|
| **P0** | | |
| 1 | Scaffold repo, docker-compose Postgres, CI | ✅ |
| 2 | DB layer + Alembic | ✅ |
| 3 | Provider abstraction + registry + `provider_fetch_log` | ✅ |
| 4 | Upstox provider + token manager | ✅ (token is semi-manual by design) |
| 5 | NSE Bhavcopy provider (EOD spine + delivery %) | ✅ |
| 6 | Corporate-action ingestion + price adjustment | ✅ (splits/bonuses only — see §9.1) |
| 7 | Indicator engine (DMA/RSI/MACD/volatility/drawdown/relative) | ✅ |
| 8 | Search + company-page API | ✅ |
| 9 | Frontend: tokens, layout, search, company page | ✅ |
| 10 | Fundamentals provider + panels with coverage flags | ✅ |
| 11 | News provider + dedup + panel | ✅ |
| 12 | Opportunity screens (Layer 1) + Finder UI | ✅ |
| 13 | Scoring engine + breakdown UI + input snapshotting | ✅ |
| 14 | Attention ranking (Layer 2) | ✅ |
| 15 | Deploy | ⚠️ **Runbook written and locally proven; not executed on a public host.** See §8 |
| **P1** | | |
| 16 | Auth (JWT) | ✅ |
| 17 | Portfolio + Zerodha CSV import | ✅ **extended to multi-broker** (Zerodha + Upstox, consolidated) |
| 18 | Watchlist | ✅ |
| 19 | AI single-company analysis | ✅ code complete; ⚠️ **blocked at runtime by a restricted API key** — §8.2 |
| 20 | Thesis Tracker | ✅ |
| — | Provenance UI polish | ✅ |
| **P2** | | |
| 21 | Historical event/recovery engine | ✅ (commit `88438e5`) |
| 22 | Advanced combinable screener | ✅ |
| 23 | Full industry scoring profiles | ✅ (see §9.4 on why only 2 profiles exist) |
| 24 | Intelligent alerts (incl. thesis triggers) | ✅ |
| 25 | NL research assistant | ❌ **Blocked** on the Gemini key — §8.2 |
| 26 | Score backtesting | ❌ Not started |
| 27 | Upstox intraday / WebSocket | ❌ Not started |
| — | Peer-percentile normalization (§X.4) | ❌ Not started |

### 4.2 API surface (39 endpoints)

**Public, provenance-enveloped:**
`GET /health` · `/assets/search` · `/quotes` · `/companies/{symbol}` ·
`/companies/{symbol}/prices` · `/technicals` · `/fundamentals` · `/news` ·
`/corporate-actions` · `/score` · `/ai-summary` · **`/historical-events`** ·
`/opportunities` · `/opportunities/screens` · `/opportunities/industries`

**Authenticated (bare JSON):**
`POST /auth/register|login|refresh|logout` · `GET /auth/me` ·
`GET|POST|DELETE /watchlist` · `GET|POST|PUT|DELETE /theses` ·
`GET|POST|PUT|DELETE /portfolio` + `POST /portfolio/import` ·
`GET /alerts` + `POST /alerts/read` · `POST /screener/run` ·
`POST /companies/{symbol}/ai-summary`

**Admin (gated by `X-Admin-Token`):** `POST /admin/upstox/token` · `GET /admin/metrics`

### 4.3 Engines (pure, no IO)

| Package | Contents |
|---|---|
| `indicators/` | `sma`, `ema`, `rsi`, `macd`, `historical_volatility`, `daily_returns`, `drawdown_series`, `max_drawdown`, relative strength/volume |
| `opportunity/` | `Screen` ABC + 10 registered screens, Kleene 3-valued condition-tree evaluator, pure metric helpers, Layer-2 attention ranking |
| `scoring/` | 6 components, coverage-renormalizing aggregator, versioned weight profiles |
| `thesis/` | `evaluate_trigger` — returns `None` for "cannot evaluate", never a false "not matched" |
| `historical/` | `detect_episodes` (peak→trough→recovery segmentation), `rank_comparables` |
| `adjustment.py` | Corporate-action price adjustment (splits + bonuses) |
| `csv_import.py` | Broker CSV parsing (Zerodha + Upstox formats) |

**Registries:** 10 opportunity screens · 28 screenable/triggerable metrics
(7 price, 9 technical, 3 valuation, 9 fundamental) · 6 score components ·
2 score profiles · 10 screener preset trees.

### 4.4 Providers (the only place external IO happens)

`upstox` (prices + instruments) · `nse_bhavcopy` (auth-free EOD spine +
delivery %) · `nse_indices` (Nifty 500 constituents) · `nse_sector_pe`
(official sector P/E) · `yfinance_quotes` (live-ish quotes) ·
`yfinance_fundamentals` · `yfinance_actions` (corporate actions) ·
`google_news` (RSS) · `gemini_summary` (LLM) · `upstox_token_manager`.

Every call is (or should be) recorded to `provider_fetch_log` for health
monitoring — this is what makes a dead provider visible.

### 4.5 Database — 23 tables

`asset` · `instrument_map` · `industry` · `company` · `price_ohlcv` ·
`provider_fetch_log` · `financial_statement` · `financial_metric` ·
`sector_index_pe` · `corporate_action` · `news_article` · `company_ai_summary` ·
`score_profile` · `score` · `score_component` · `app_user` · `refresh_token` ·
`watchlist_item` · `thesis` · `thesis_trigger` · `thesis_event` · `holding` ·
`alert`

14 Alembic migrations. Schema in CI comes from migrations (not `create_all`),
so model/migration drift fails in CI rather than on deploy.

### 4.6 Frontend

**Pages:** `/` (market overview) · `/company/[symbol]` · `/opportunities` ·
`/opportunities/advanced` · `/portfolio` · `/theses` `/theses/new` `/theses/[id]` ·
`/alerts` · `/login` · `/register` · `/upstox-callback`

**28 domain components**, 5 terminal primitives (`Panel`, `Delta`, `Stat`,
`RangeBar`, `Sparkline`), 15 BFF route handlers.

### 4.7 Live data coverage (the developer's prod container, 2026-08-26)

| Table | Rows |
|---|---|
| Active NSE equities | **500** (+41 ETFs, excluded from screens) |
| `price_ohlcv` | **984,796** — 2021-08-25 → 2026-08-26, ~1,078 bars/company |
| `corporate_action` | 15,452 |
| `score` / `score_component` | 2,718 / 13,590 (1,176 assets scored) |
| `financial_metric` / `financial_statement` | 6,394 / 197 |
| `sector_index_pe` | 164 |
| `news_article` | 354 — **only ~1 month deep, all `event_type` NULL** |
| `company_ai_summary` | 2 |
| `provider_fetch_log` | 1,275 |
| `app_user` / `holding` / `watchlist_item` | 10 / 3 / 9 |
| `thesis` / `alert` | 0 / 0 |

### 4.8 Quality gates

**607 test functions across 63 files.** CI (`.github/workflows/ci.yml`) runs
on every push to `main` and every PR, with a real Postgres service container:
`ruff check .` → `mypy app` → `alembic upgrade head` → `pytest`.
Frontend gates are `npm run lint`, `npx tsc --noEmit`, `npm run build`.

---

## 5. Getting it running on your machine

### 5.1 Fastest path — the whole stack in containers

```bash
podman compose -f docker-compose.prod.yml up -d --build
```

Frontend <http://localhost:3100>, backend <http://localhost:8000>. Isolated
from the dev compose file: own project name, own volume, Postgres on **5433**
(dev is on 5432). Bringing it up will not touch a dev database.

A fresh database is empty. Seed it — the universe first, then prices:

```bash
podman compose -f docker-compose.prod.yml exec backend python -m app.services.universe
```
```bash
podman compose -f docker-compose.prod.yml exec backend python -m app.jobs.backfill_history --days 365
```

Then scores (slow — ~2.5 s/asset for a live fundamentals fetch, so ~20 min for
the Nifty 500):

```bash
podman compose -f docker-compose.prod.yml exec backend python -m app.jobs.daily_ingestion
```

Until scores exist the screener still works: it ranks scored rows first and
shows `–` for the rest, by design.

### 5.2 Bare-metal development

```bash
cd backend && uv sync --group dev && cp .env.example .env && uv run uvicorn app.main:app --reload
```
```bash
cd frontend && npm install && cp .env.example .env && npm run dev
```

Backend on :8000, frontend on :3000, dev Postgres via `docker-compose.yml` on
:5432. `JWT_SECRET` has **no default** — the app refuses to start without one,
deliberately (a weak default would let anyone forge a session):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 5.3 Environment variables

| Key | Required? | Notes |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql+psycopg://...` — note the `+psycopg` driver |
| `JWT_SECRET` | **yes, no default** | app won't boot without it |
| `CORS_ORIGINS` | yes in prod | comma-separated; must list the frontend's public URL |
| `ADMIN_TOKEN` | for `/admin/*` | unset simply leaves admin routes unreachable |
| `GEMINI_API_KEY` | for AI summary | **currently restricted — §8.2** |
| `UPSTOX_API_KEY` / `_SECRET` / `_REDIRECT_URI` | for Upstox data | Bhavcopy covers EOD without it |
| `ENABLE_SCHEDULER` | off by default | `true` only on an always-on instance |
| `DAILY_INGESTION_HOUR_IST` | default `20` | 20:00 IST, after Bhavcopy publishes |
| `API_BASE_URL` (frontend) | yes in prod | backend URL + `/api/v1` |

Root `.env` (gitignored) feeds `${VAR}` substitution into
`docker-compose.prod.yml`: currently `GEMINI_API_KEY` and `JWT_SECRET`.

---

## 6. Where to find what

| Doc | Purpose |
|---|---|
| `SUMMARISER.md` (this) | Status + handover — start here |
| `Build_plan.md` | The detailed build plan, §A–§X. Step status is in §S |
| `Screener.md` | **Declared source of truth** for product behaviour |
| `Deployment.md` | Step-by-step hosting runbook (not yet executed) |
| `API_Sources.md` | Every data source, fallbacks, trust tiers, paid options |
| `architecture.md` | System architecture in depth |
| `founder_vision.md` | The "why" |
| `product_principles.md` | The rules we build by, incl. approved/banned language |
| `data_strategy.md` · `roadmap.md` · `decision_log.md` | Sourcing · milestones · irreversible decisions |

---

## 7. Conventions a new contributor must know

1. **Never fabricate.** `None` over a guess, everywhere. If you add a metric,
   it must return `None` when its inputs are missing.
2. **Engines are pure.** No `sqlalchemy`, no `httpx`, no `app.services` imports
   inside `app/engines/`.
3. **Units are load-bearing and go in the name.** `*_pct` is a **percent**;
   fractions get a different name. This has been a live bug three times —
   `TechnicalSnapshot.drawdown_pct` is still a *fraction* despite its name, and
   `app/services/scoring.py` multiplies it by 100 to feed `ScoreInputs`. New
   code follows the strict rule; that one legacy field is the exception.
4. **Weights are versioned configuration, never code constants.** They live in
   `score_profile.weights` in the DB.
5. **Docstrings explain *why*, and cite the spec section and the bug that
   motivated the design.** Match the surrounding density — it is unusually high
   here on purpose.
6. **Ownership-scoped queries return 404, never 403.**
7. **Corporate-action adjustment is mandatory** on any multi-day price read.
   Go through `get_adjusted_bars` / `load_universe_bars_with_ids`; a hand-rolled
   loader reports a fabricated −50% on every split day.
8. **`backend/data.sql` and `backend/data copy.sql` are an intentional local
   backup and must never be committed.** They are now in `.gitignore`; do not
   remove those lines.

---

## 8. Pending — operational

### 8.1 Public hosting — NOT DONE

The app has never been deployed to a public URL. Everything below is
outstanding. `Deployment.md` is a complete runbook and the container images
are proven locally, so this is account creation and env wiring, not code.

- [ ] **Database:** create a Supabase or Neon project. Use the **direct**
      (non-pooled) string for Alembic and, on Supabase, the **pooled
      transaction-mode (port 6543)** string for runtime. Convert to
      `postgresql+psycopg://…?sslmode=require`.
- [ ] **Backend:** Render or Fly.io, building `backend/Dockerfile` (multi-stage
      `uv`, ~217 MB, non-root). Health check `/api/v1/health`. Set every var in
      §5.3 plus `ENABLE_SCHEDULER=true`.
- [ ] **Frontend:** Vercel, project root `frontend`, set `API_BASE_URL`.
- [ ] **Add the Vercel URL to the backend's `CORS_ORIGINS`** — otherwise fetches
      fail silently in the console, not visibly on the page.
- [ ] **Seed the hosted DB** (`universe` → `backfill_history` → `daily_ingestion`).
- [ ] **No deploy configs exist yet** — there is no `vercel.json`, `render.yaml`,
      `fly.toml` or `Procfile` in the repo. Each host is expected to
      auto-detect; add config files if you want the deploy reproducible.
- [ ] Work through the §7 smoke-test checklist in `Deployment.md`.

### 8.2 API keys

**Gemini — BROKEN, and it blocks step 25.**
The key in `backend/.env` is valid for reads but **cannot generate**.
`GET /v1beta/models` returns 200 in ~0.6 s and lists 40+ models, but
`POST …:generateContent` either hangs with zero bytes received or returns an
empty-bodied 404 — identically from the host and from inside the container,
with Google's own `server: scaffolding on HTTPServer2` header. Not a code,
network, or model-name problem; the `vary: Referer` header points at an
**API-key restriction in the Google Cloud console**.

> **Fix:** in the console, set the key's Application restrictions to *None* and
> ensure API restrictions allow the Generative Language API — or issue a fresh
> unrestricted key. The exact one-command re-test is in
> `backend/app/providers/ai/gemini_summary.py`'s module docstring.

The failure path itself was hardened in `eb449e8`, so a broken key now fails in
≤45 s (was ~94 s), is negative-cached for 10 minutes, is recorded to
`provider_fetch_log`, and surfaces the provider's real message in the UI.

**Upstox — works, but two manual steps are permanent by design:**
- The access token expires daily ~03:30 IST and Upstox issues no refresh token.
- **A backend restart or redeploy also clears it** — it is in-memory, never
  DB-backed, and the manager never stores your password/PIN/TOTP.
- Re-auth is a 3-step manual flow (§5 of `Deployment.md`). NSE Bhavcopy is
  auth-free and covers the EOD price spine meanwhile, so nothing breaks — only
  Upstox-only data goes stale.
- Automating this would mean a DB-backed token store; deliberately out of scope.

**No other paid keys.** yfinance, NSE Bhavcopy, NSE indices, and Google News
RSS are all free and unauthenticated.

### 8.3 Security / ops gaps

- [ ] **No rate limiter anywhere.** The auth gate is currently the only bound on
      abuse — `POST /screener/run` and `POST /ai-summary` both rely on it. The
      spec asks for one three times.
- [ ] `/admin/*` is a shared-secret header, not real RBAC.
- [ ] No error tracking (Sentry or equivalent) and no uptime monitoring.
- [ ] No backup/restore policy for the hosted database.
- [ ] SEBI positioning: the disclaimer copy exists in the UI footer, but the
      research-analyst positioning decision has not been formally signed off
      (`Build_plan.md` §V.6).

---

## 9. Pending — known data & product gaps

### 9.1 Corporate actions are incomplete (highest-impact data bug)

The `yfinance_actions` feed **misses bonus issues and demergers**. The
adjustment engine itself is correct — verified live. Measured examples:

| Symbol | Date | Residual unexplained session | Cause |
|---|---|---|---|
| BAJFINANCE | 2025-06-16 | −79.9% | 4:1 bonus missing; only the 1:2 split on file |
| ABFRL | 2025-05-22 | −66.6% | demerger; **no non-dividend action on file at all** |
| VEDL | 2026-04-30 | −64.9% | demerger; none on file |
| 360ONE | 2023-03-02 | −50.3% | raw close 1773.30 → 441.05 (4×); only a 2× split on file |
| BAJAJFINSV | 2022-09-13 | −47.9% | 1:1 bonus missing |
| SIEMENS | 2025-04-07 | −42.9% | Siemens Energy India demerger |

Scale: of 1,306 detected falls across the universe, 32 (2.5%) contain a single
session ≤ −20% and 13 (1.0%) ≤ −25%; the deepest are dominated by these.

**Impact is not limited to the new panel** — DMAs, RSI, volatility, drawdown,
the `down_*` screens, `technical_setup` in the score, and the chart itself are
all wrong for these names in the affected windows. The historical-falls panel
surfaces it (`worst_session_pct`) rather than hiding it, which is how it was
found. **Fix needs a corporate-actions source that reports bonuses and
demergers — NSE's own endpoint is the obvious candidate.**

### 9.2 Fundamentals are single-source and shallow

One provider (yfinance), always rendered at low confidence, fields omitted
rather than estimated. This was flagged as the project's #1 risk from day one
and remains true. An XBRL parser is the real fix.

### 9.3 News is one month deep and unclassified

354 articles, 2026-07-25 → 2026-08-26, across 20 assets, and **every
`event_type` is NULL**. Consequences: the historical engine can compare only
3 of Screener.md §10's 7 dimensions (magnitude, duration, volatility — the
other four are *declared* as unavailable in the API payload rather than
silently dropped), and the "why did it fall?" narrative has no event taxonomy
to draw on.

### 9.4 Only 2 of the planned industry scoring profiles exist

`default` and `financials`. This is a deliberate, documented refusal rather
than unfinished work: a profile earns its existence only when a component's
*normalization is structurally invalid* for that sector, never by nudging
weights on metrics that mean the same thing everywhere. `financials` clears
that bar on measured evidence (D/E median 1.81× vs 0.08–0.49× elsewhere).
`information-technology` and `manufacturing` were tested and rejected. Full
reasoning in `app/engines/scoring/registry.py`'s docstring.

The genuine gap this leaves is **peer-percentile normalization** (§X.4, still
unbuilt): thresholds inside components are absolute, so the technical half of
the score is exactly comparable across industries and the fundamental half is
only approximately so.

### 9.5 Deferred by design, with reasons recorded

- **`historical_event` table + job.** Not cached because an episode is not a
  stable fact: `recovered`/`recovery_date` change as bars arrive, and a past
  fall's magnitude changes *retroactively* when a missing split is discovered.
  A cached row would disagree with the chart above it on the same page.
- **Layer-2 "historical analog recovered?" annotation.** Blocked not by the
  missing table but because screen runs size their window with
  `calendar_lookback_for(required_bars)` (~1 year), so there is no multi-year
  history in memory to detect episodes in.
- **Feeding episodes into the AI summary prompt.** Would change `_source_hash`
  and regenerate every summary; also pointless while the LLM is down.
- **`historical` scoring component** (listed at `Build_plan.md:347`) — needs the
  cross-universe path above.

### 9.6 Developer-environment gotcha

The podman VM's clock drifts behind the host after the Mac sleeps (13m33s
observed on 2026-08-26). The symptom is exactly one failing test —
`test_company_summary.py::test_a_recent_failure_short_circuits_without_calling_the_provider`
— because it is the only test whose timestamp is written by Postgres
(`server_default func.now()`) and then compared against Python's clock.
**It is not a code regression.** Fix:

```bash
podman machine stop && podman machine start
```

Note the underlying fragility: `_recently_attempted` (`prices.py`) and
`_recently_failed` (`company_summary.py`) both compare two clocks that can
disagree.

---

## 10. Suggested next steps

1. **Fix the Gemini key** (§8.2) — one console change, unblocks step 25.
2. **Fix corporate actions** (§9.1) — highest-impact data correctness work;
   it silently corrupts indicators for a handful of large names today.
3. **Deploy publicly** (§8.1) — the runbook is written and the images are proven.
4. **Add a rate limiter** (§8.3) before the app is public.
5. Then the remaining P2: step 26 (score backtesting), step 27 (Upstox
   intraday/WebSocket — needs API access), peer-percentile normalization.
