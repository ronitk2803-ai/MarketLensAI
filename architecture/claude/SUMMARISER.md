# SUMMARISER — Project Status & Handover (`mlai` / MarketLens AI)

> **Read this first.** What we're building, what is *actually built*, what is
> pending, and how to get it running on your machine. Codename `mlai`; the
> product name in the UI is **MarketLens AI**. Nothing is hard-coded to a brand.
>
> **Status as of 2026-08-31:** P0 and P1 complete. **P2 is 5 of 7 numbered
> steps done**, plus peer-percentile normalization (§X.4) and a general rate
> limiter. Every feature in the build plan that can be built without a
> third-party account is now built — the NL research assistant (step 25,
> §X.8) was the last one. Auth is extended beyond the original P1 scope with
> email verification, password reset and Google sign-in. The
> corporate-actions data gap (§9.1, the highest-impact known data bug) is
> fixed — and the backfill is now **run against the podman prod stack**, not
> just code-complete. Both Gemini bugs (§8.2) are fixed too; the AI company
> summary and the research assistant are genuinely live, verified end-to-end.
> A full re-verification pass on 2026-08-31 — all gates green (943 tests);
> live prices, AI, and every page confirmed working — is in §11.5.
>
> **DEPLOYED AND LIVE at <https://marketlensai.in> (2026-08-31).** The whole
> stack is hosted on free tiers — Neon Postgres (Singapore) + Render (backend,
> free) + Vercel (frontend, Hobby) + Resend (email, domain verified) + a
> cron-job.org keep-alive + a GitHub Actions nightly ingestion job. Google
> sign-in **was broken on the live site and is fixed pending deploy** — see
> §8.4, though §8.6's OOM is the likelier root cause of it. The backend was
> **OOM-killed 8 times** on the 512 MB free instance (confirmed against
> Render's own logs); fixed 2026-09-01 (§8.6), with a related connection-
> pool exhaustion also fixed (§8.7). **The hosted DB was freshly seeded**
> (500 companies, ~150k
> price bars over 450 days, corporate actions, 500 scores). See §8.1 for the
> live URLs and §11.6 for the deployment story; the granular blow-by-blow is
> in `DEPLOY_STATUS.md`.
>
> **Deploy repo is `github.com/ronitk2803-ai/MarketLensAI`**, NOT
> `safiyat/ronrack` (the dev's hosting accounts had no access to the latter).
> The local clone has two remotes — `origin` = safiyat/ronrack, `mine` =
> ronitk2803-ai/MarketLensAI — and **every push must go to both**
> (`git push origin main && git push mine main`); Render/Vercel auto-deploy
> from `mine`.
>
> **Post-deploy cleanup done 2026-08-31:** the §7 smoke test has been run
> against the live site, the cron-job.org keep-alive ping is now every 5 min
> (was 10 — the free dyno went cold between pings), and the Neon password
> has been reset.
>
> **Left to polish (not blockers):** the Render free dyno still cold-starts
> (~20-45s) on the first hit after a genuinely idle stretch, which the 5-min
> ping and a Vercel 60s function timeout absorb — moving Render to the
> ~$7/mo Starter plan removes both problems and lets `ENABLE_SCHEDULER=true`
> replace the GitHub Actions job.
>
> **New to this project? Read §11 first** — it is the "where we are right
> now and what to do next" section written for exactly that.

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
PostgreSQL 16 (24 tables)
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
| 6 | Corporate-action ingestion + price adjustment | ✅ (NSE primary since 2026-08-29 — see §9.1) |
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
| 16 | Auth (JWT) | ✅ **extended**: email verification, password reset, Google sign-in |
| 17 | Portfolio + Zerodha CSV import | ✅ **extended to multi-broker** (Zerodha + Upstox, consolidated) |
| 18 | Watchlist | ✅ |
| 19 | AI single-company analysis | ✅ code complete and **live** — the Gemini auth bug is fixed, §8.2 |
| 20 | Thesis Tracker | ✅ |
| — | Provenance UI polish | ✅ |
| **P2** | | |
| 21 | Historical event/recovery engine | ✅ (commit `88438e5`) |
| 22 | Advanced combinable screener | ✅ |
| 23 | Full industry scoring profiles | ✅ (see §9.4 on why only 2 profiles exist) |
| 24 | Intelligent alerts (incl. thesis triggers) | ✅ |
| 25 | NL research assistant | ✅ 2026-08-30 — see `Build_plan.md` §X.8 |
| 26 | Score backtesting | ❌ Not started |
| 27 | Upstox intraday / WebSocket | ❌ Not started |
| — | Peer-percentile normalization (§X.4) | ✅ 2026-08-29 |

### 4.2 API surface (40 endpoints)

**Public, provenance-enveloped:**
`GET /health` · `/assets/search` · `/quotes` · `/companies/{symbol}` ·
`/companies/{symbol}/prices` · `/technicals` · `/fundamentals` · `/news` ·
`/corporate-actions` · `/score` · `/ai-summary` · **`/historical-events`** ·
`/opportunities` · `/opportunities/screens` · `/opportunities/industries`

**Authenticated (bare JSON):**
`POST /auth/register|login|refresh|logout` · `GET /auth/me` ·
`POST /auth/verify-email/send|confirm` · `POST /auth/password-reset/request|confirm` ·
`GET /auth/providers` · `GET /auth/google/authorize-url` · `POST /auth/google/callback` ·
`GET|POST|DELETE /watchlist` · `GET|POST|PUT|DELETE /theses` ·
`GET|POST|PUT|DELETE /portfolio` + `POST /portfolio/import` ·
`GET /alerts` + `POST /alerts/read` · `POST /screener/run` ·
`POST /companies/{symbol}/ai-summary` · `POST /assistant/ask`

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
(official sector P/E) · `nse_actions` (corporate actions, primary since
2026-08-29) · `yfinance_quotes` (live-ish quotes) · `yfinance_fundamentals` ·
`yfinance_actions` (corporate actions fallback) · `google_news` (RSS) ·
`gemini_summary` (LLM, one-shot) · `gemini_chat` (LLM, tool-calling) ·
`upstox_token_manager` · `resend` (transactional email) ·
`google_oauth` (user sign-in).

Every call is (or should be) recorded to `provider_fetch_log` for health
monitoring — this is what makes a dead provider visible.

### 4.5 Database — 24 tables

`asset` · `instrument_map` · `industry` · `company` · `price_ohlcv` ·
`provider_fetch_log` · `financial_statement` · `financial_metric` ·
`sector_index_pe` · `corporate_action` · `news_article` · `company_ai_summary` ·
`score_profile` · `score` · `score_component` · `app_user` · `refresh_token` ·
`watchlist_item` · `thesis` · `thesis_trigger` · `thesis_event` · `holding` ·
`alert` · `auth_code`

16 Alembic migrations. Schema in CI comes from migrations (not `create_all`),
so model/migration drift fails in CI rather than on deploy.

### 4.6 Frontend

**Pages:** `/` (market overview) · `/company/[symbol]` · `/opportunities` ·
`/verify-email` · `/forgot-password` ·
`/opportunities/advanced` · `/portfolio` · `/theses` `/theses/new` `/theses/[id]` ·
`/alerts` · `/login` · `/register` · `/upstox-callback` · `/research`

**28 domain components**, 5 terminal primitives (`Panel`, `Delta`, `Stat`,
`RangeBar`, `Sparkline`), 15 BFF route handlers.

### 4.7 Live data coverage (the developer's prod container, 2026-08-26)

> **Update 2026-08-31:** `backfill_corporate_actions` has now been run against
> this container (§9.1's open item). `corporate_action` is 15,591 rows —
> 3,817 from `nse_actions` — and now includes **81 bonuses, 25 rights, 18
> demergers** yfinance never had; BAJFINANCE/BAJAJFINSV/ABFRL/SIEMENS
> adjusted charts verified smooth across their ex-dates. `price_ohlcv` runs
> to 2026-08-28. Other rows below are the 2026-08-26 snapshot.

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

**778 test functions across 76 files — 943 tests collected and passing**
(the gap is parametrized cases). CI (`.github/workflows/ci.yml`) runs on every
push to `main` and every PR, with a real Postgres service container:
`ruff check .` → `mypy app` → `alembic upgrade head` → `pytest`.
Frontend gates are `npm run lint`, `npx tsc --noEmit`, `npm run build`.

**All gates verified green 2026-08-31**, immediately before this handover:
`ruff` clean, `mypy app` clean across 109 source files, 943 tests passing in
~2m19s, and the frontend `lint` / `tsc --noEmit` / `build` all clean.

---

## 5. Getting it running on your machine

### 5.1 Fastest path — the whole stack in containers

```bash
podman compose -f docker-compose.prod.yml up -d --build
```

Frontend <http://localhost:3000>, backend <http://localhost:8000>. The DB is
isolated from the dev compose file — own project name, own volume, Postgres
on **5433** (dev is on 5432), so bringing it up will not touch a dev
database. The frontend port (3000) is deliberately the *same* as bare-metal
dev, so one localhost Google OAuth redirect URI covers both — run this stack
**or** `npm run dev`, not both.

A fresh database is empty. Seed it — universe, then prices, then corporate
actions:

```bash
podman compose -f docker-compose.prod.yml exec backend python -m app.services.universe
```
```bash
podman compose -f docker-compose.prod.yml exec backend python -m app.jobs.backfill_history --days 365
```
```bash
podman compose -f docker-compose.prod.yml exec backend python -m app.jobs.backfill_corporate_actions
```

The third pulls full split/bonus/demerger history from NSE — without it the
adjusted chart and indicators are wrong on any stock with a bonus or
demerger yfinance missed (§9.1). Then scores (slow — ~2.5 s/asset for a live
fundamentals fetch, so ~20 min for the Nifty 500):

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
| `GEMINI_API_KEY_1` (`_2`/`_3`/`_4` optional) | for AI summary + NL assistant | fallback pool, §8.2 — live and working |
| `UPSTOX_API_KEY` / `_SECRET` / `_REDIRECT_URI` | for Upstox data | Bhavcopy covers EOD without it |
| `ENABLE_SCHEDULER` | off by default | `true` only on an always-on instance |
| `DAILY_INGESTION_HOUR_IST` | default `20` | 20:00 IST, after Bhavcopy publishes |
| `API_BASE_URL` (frontend) | yes in prod | backend URL + `/api/v1` |

Root `.env` (gitignored) feeds `${VAR}` substitution into
`docker-compose.prod.yml`: currently `GEMINI_API_KEY_1`..`_4` and `JWT_SECRET`.

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

### 8.1 Public hosting — DONE 2026-08-31

Live at **<https://marketlensai.in>**. Full step log: `DEPLOY_STATUS.md`.

| Piece | Where | Notes |
|---|---|---|
| Frontend | Vercel Hobby, project `market-lens-ai`, team "MLAI", root dir `frontend` | env `API_BASE_URL=https://mlai-backend.onrender.com/api/v1`. `next.config.ts` skips `output:"standalone"` when `VERCEL=1`. Data-heavy pages set `maxDuration=60`. |
| Backend | Render free, service `mlai-backend`, `https://mlai-backend.onrender.com` | Docker, Singapore, `ENABLE_SCHEDULER=false`. **Cold-starts ~20-45s** after idle. Blueprint from `render.yaml` but env vars were set by hand. |
| Database | Neon free, Singapore, PG17 | pooled string works for both Alembic and runtime. Seeded: 500 companies, ~150k bars (450d), corp actions, 500 scores. |
| Keep-alive | cron-job.org hits `/api/v1/health` | **every 5 min** since 2026-08-31 (was 10 — the dyno went cold between 10-min pings). |
| Nightly ingestion | GitHub Actions `nightly-ingestion.yml` on `MarketLensAI` | secrets `DATABASE_URL` + `JWT_SECRET`; runs 20:00 IST. First manual run was green. |
| Email | Resend, `marketlensai.in` verified | sender `MarketLens AI <noreply@marketlensai.in>` (a real GoDaddy mailbox). |
| Google OAuth | one client, redirect `https://marketlensai.in/api/auth/google/callback` | config verified correct 2026-09-01 (Google accepts the client id/secret/redirect URI). Sign-in was nevertheless **failing live** — §8.4. |
| DNS | GoDaddy: `A @ 216.198.79.1` (Vercel). `CNAME www` still points to apex. | domain had a WHOIS "status hold" that had to be cleared first; a GoDaddy Website Builder draft site had to be deleted to free the `A` record. |

- [x] Done 2026-08-31: the §7 smoke test has been run against the live
      site; the keep-alive ping moved from 10 min to **5 min**; the **Neon
      password has been reset** (an early connection string had been pasted
      in chat — anything holding the old string, i.e. Render's
      `DATABASE_URL` and the GitHub Actions `DATABASE_URL` secret, must carry
      the new one).
- [ ] Still to do: consider Render Starter (~$7/mo) to kill cold-starts and
      let `ENABLE_SCHEDULER=true` replace the Actions job; re-add
      `www.marketlensai.in` in Vercel if wanted.

Deploy configs `render.yaml`, `backend/fly.toml` (unused alternative) and
`frontend/vercel.json` now exist in the repo.

### 8.2 API keys

**Gemini — FIXED 2026-08-30. Unblocks steps 19 (runtime) and 25.** Two
separate bugs, discovered on two different nights, each looking identical
to the other from the outside (a 502/hang after a long wait):

1. **Auth method (fixed 2026-08-28).** The app authenticated with a
   `?key=` query parameter; Google's newer "account-bound" key type
   (tied to a service account, created via the current Cloud Console
   flow) hangs indefinitely on that auth method no matter how the console
   restrictions are set. First misdiagnosed as a console API-key
   restriction (`GET /v1beta/models` 200s in ~0.6s, `POST
   .../generateContent` hangs with zero bytes — exactly what a
   referrer-restricted key looks like). Fix: `x-goog-api-key` header
   instead of the query param.
2. **Model overload (fixed 2026-08-30).** After (1), the identical
   symptom kept recurring — this time it was `gemini-flash-latest`
   itself, genuinely and commonly overloaded (clean, fast `503
   UNAVAILABLE` responses, live, repeatedly, across **two separate
   Google accounts' keys**), not the key or its auth. `gemini-flash-
   lite-latest` answered instantly and correctly on both of the same
   keys, including full native function-calling round trips. Fix:
   `MODEL_FALLBACK_CHAIN` tries `gemini-flash-lite-latest` first, and a
   `(model, key)` fallback loop (`GEMINI_API_KEY_1`..`_4`, up to 4 keys)
   cycles through every combination — models outer, keys inner — before
   giving up.

Verified live end to end: the actual `GeminiSummaryProvider.generate()`
class, unmodified logic, called with real keys and returned a real model
response, and a full function-calling round trip (tool call → tool
result → grounded final answer) succeeded on the same reliable model.

> **Fix, already applied:** `backend/app/providers/ai/gemini_summary.py`
> now sends the key via `headers={"x-goog-api-key": ...}` instead of
> `params={"key": ...}`. No console change was actually needed — the key's
> restrictions were already correct (Application: None, API: Gemini API)
> the whole time. If a *future* key genuinely is console-restricted, the
> header form fails the same way the query form used to; the module
> docstring's diagnostic now checks both to tell the two apart.

The failure path itself was hardened in `eb449e8`, so a broken key now fails in
≤45 s (was ~94 s), is negative-cached for 10 minutes, is recorded to
`provider_fetch_log`, and surfaces the provider's real message in the UI.

**Resend — KEY OBTAINED (2026-08-31), domain NOT verified.** A real
`re_…` key is set in `backend/.env` and the repo-root `.env`. Not tested
with a live send from here. `RESEND_FROM_EMAIL` is still the default
`onboarding@resend.dev`, so the owner-only-delivery constraint below is
fully in force — **no real user can complete signup yet.** Without a key at
all, both flows fail with an honest `502 [resend] RESEND_API_KEY not
configured` rather than silently doing nothing.

> **The constraint that will bite you:** until a domain is verified at
> resend.com/domains, the default `onboarding@resend.dev` sender delivers
> **only to the address that owns the Resend account** and returns 403 for
> everyone else. So it works perfectly while you test with your own address
> and fails for every real user. Verify a domain and point
> `RESEND_FROM_EMAIL` at an address on it before anyone else can sign up.
> The provider translates that 403 into a message naming the fix.

**Google OAuth — CONFIGURED for local (2026-08-31).** A client is set up and
`GET /auth/providers` returns `{"google": true}`, so the sign-in button
shows. Verified only that far — an actual browser sign-in round trip has
not been re-tested. A hosted deploy still needs its own domain added as a
redirect URI (see below).

> **Set up / add an environment:** an OAuth client at
> console.cloud.google.com → APIs & Services → Credentials → OAuth client ID
> → Web application. Local dev and the prod container share
> `http://localhost:3000/api/auth/google/callback` (the container frontend
> is on 3000 too — see §5.1); a hosted deploy adds
> `https://marketlensai.in/api/auth/google/callback` as a second registered
> URI. Google treats each as distinct and permits plain `http` only for
> `localhost`/`127.0.0.1`. Then set `GOOGLE_CLIENT_ID`,
> `GOOGLE_CLIENT_SECRET` and `GOOGLE_REDIRECT_URI` (byte-identical to the
> registered URI for that environment).

**Upstox — works, but two manual steps are permanent by design:**
- The access token expires daily ~03:30 IST and Upstox issues no refresh token.
- **A backend restart or redeploy also clears it** — it is in-memory, never
  DB-backed, and the manager never stores your password/PIN/TOTP.
- Re-auth is a 3-step manual flow (§5 of `Deployment.md`). NSE Bhavcopy is
  auth-free and covers the EOD price spine meanwhile, so nothing breaks — only
  Upstox-only data goes stale.

**No other paid keys.** yfinance, NSE Bhavcopy, NSE indices, and Google News
RSS are all free and unauthenticated.

### 8.3 Security / ops gaps

- [x] **General rate limiter — done.** `app/core/rate_limit.py`: an
      in-memory token bucket, two layers — a global ASGI-middleware backstop
      on every route (~60/min per user-or-IP) plus tighter per-route ceilings
      on Tier A/C routes (`/screener/run` ~3/hr, `/opportunities` ~20/min,
      `/ai-summary` ~5/day, `/auth/register|login`, password-reset request).
      `TRUST_FORWARDED_FOR` (default `false`) must be set `true` on
      Render/Fly — see `Deployment.md` — or every visitor behind the host's
      proxy shares one IP-keyed bucket.
- [ ] `/admin/*` is a shared-secret header, not real RBAC.
- [ ] No error tracking (Sentry or equivalent) and no uptime monitoring.
- [ ] No backup/restore policy for the hosted database.
- [ ] SEBI positioning: the disclaimer copy is now live across the whole app
      (footer, every AI/scoring panel footnote, and transactional emails —
      2026-08-29), but the research-analyst **positioning decision** itself
      has not been formally signed off (`Build_plan.md` §V.6). That is a
      business/legal judgment call, not a coding task.
- [ ] **No full security audit has been completed.** One was launched
      2026-08-31 (8 parallel reviewers: authn, authz, LLM/prompt-injection,
      injection/validation, SSRF/secrets, DoS/rate-limit, frontend/BFF,
      correctness) but **every agent aborted on a usage limit before
      producing findings** — so it produced *no result at all*, neither a
      clean bill of health nor a list of issues. **Do not read the absence
      of findings as an absence of problems.** Re-run it before going
      public; the highest-value targets are the newest code
      (`research_assistant.py`'s tool dispatch and its 4 user-scoped tools,
      `gemini_chat.py`, and the `/assistant/ask` surface).

**What *was* verified live on 2026-08-31** (manual checks, not a substitute
for the audit above):

| Check | Result |
|---|---|
| Backend `/health` | 200 |
| Public endpoints (screens, industries, search) | 200 |
| `/watchlist`, `/portfolio`, `/theses`, `/alerts` unauthenticated | 401 |
| `POST /assistant/ask` unauthenticated | 401 |
| `POST /admin/upstox/token` without `X-Admin-Token` | 401 |
| BFF `/api/assistant/ask` without session cookie | 401 |
| Rate limiter on `/quotes` (cap 30/min) | 30×200 then 5×429 |
| 429 response carries `Retry-After` **and** CORS headers | yes — proves middleware ordering is right |
| CORS with a disallowed `Origin` | no `access-control-allow-origin` reflected |
| All frontend pages incl. `/research`, `/company/J%26KBANK` | 200 |
| Secrets tracked in git / baked into the image | none — `.env`, `backend/.env`, `Secrets/` all gitignored; no key in any tracked file; no `.env` in the built image |

### 8.4 Google sign-in failed live — fixed 2026-09-01 (not yet re-verified)

Reported as `/login?error=google` on the live site when signing up with
Google. **Every part of the OAuth configuration was verified correct**
against production before touching any code, which is what makes the
remaining explanation interesting:

| Probe against production | Result |
|---|---|
| `/health` | 200 in 0.6s (warm) |
| `/auth/providers` | `{"google": true}` |
| authorize URL's `redirect_uri` | `https://marketlensai.in/api/auth/google/callback` — correct |
| `POST /auth/google/callback` with a junk code | `502 [google_oauth] token exchange failed: 400 invalid_grant "Malformed auth code."` |
| DB reads (`/assets/search`, `/opportunities/screens`) | 200 — so the Neon password reset did reach Render |

The last row is the load-bearing one: `invalid_grant` means Google
**accepted** the client id, client secret and redirect URI and rejected only
the code. `invalid_client` would have meant a bad secret;
`redirect_uri_mismatch` a bad URI. Neither appeared, so none of the usual
OAuth suspects were involved.

**The cause (strong hypothesis, not observed):** commit `c06b7d5` added
`maxDuration = 60` to the three data-heavy *pages* but to **no route
handler**. On Vercel Hobby a function defaults to ~10s, and
`/api/auth/google/callback` blocks on a Render free dyno that cold-starts
20-45s — so the function was killed mid-exchange. It could not be confirmed
directly: a real sign-in can't be reproduced from a terminal, and the
handler's `catch {}` wrote nothing down anywhere.

**Fixes applied:**
- `maxDuration = 60` on **all ten** `app/api/auth/*` route handlers. Google
  was the reported one; login, register, verify-email and password-reset had
  the identical latent bug and would fail the same way on a cold dyno.
- The callback's bare `catch {}` — which collapsed a rejected grant, a 500
  from account linking, and a timeout into one message with no record — now
  logs the real reason and splits "backend never answered" (`google_
  unreachable`, "wait a few seconds and try again") from "backend rejected
  it" (`google`). **If it fails again, that log line names the cause**;
  don't re-derive it from scratch.

- [ ] **Not yet re-verified live.** The fix ships on deploy; a real browser
      sign-in still has to be run against marketlensai.in to confirm it.

### 8.5 Display name instead of email address (2026-09-01)

The header showed the signed-in account's email. It now shows the person's
name, falling back to the email when there isn't one.

- `SCOPES` in `google_oauth.py` went from `openid email` to
  `openid email profile`. **This reverses a decision the file documented**
  (`profile` was refused as buying a name "we don't display" — no longer
  true). `access_type=offline` is still refused. Consequence: existing
  Google users get a **re-consent prompt**, because the scope set changed.
- New nullable `app_user.display_name` (migration `7b1e4a92c5d0`), fed only
  from Google's `name`. Existing Google accounts backfill on next sign-in;
  a name already on file is never overwritten, so a future
  "what should we call you" setting can't be silently reverted by a re-login.
- **Password signups keep showing their email, by design.** The register
  form doesn't ask for a name and deriving one from the local part of the
  address (`ronit.k2803@…` -> "Ronit") is exactly the fabrication §7 rule 1
  forbids. So the email fallback is the common case, not an edge case. If
  names are wanted for everyone, the honest fix is a name field on the
  register form.

### 8.6 Render OOM-killed the backend (exit 137) — fixed 2026-09-01

Render alerted twice with `Exited with status 137` — SIGKILL, which on a
512 MB free instance means the OOM killer.

**Cause.** `load_universe_bars_with_ids` hydrated a full `PriceOHLCV` +
`Asset` ORM instance per price bar. Measured on the dev universe:
**3.45 KB/bar** as ORM instances vs **0.71 KB** as plain column tuples —
each instance carries its own `__dict__`, `Decimal` objects for five
`Numeric` columns, and a Session identity-map entry that keeps the whole
result alive. `frontend/app/page.tsx` then fires **four screens
concurrently** (`Promise.all`), and each loads the universe independently:

| Homepage board | Lookback | ~bars (500 assets) | Before | After §8.6 |
|---|---|---|---|---|
| `down_5d` | 18d | 6k | 20 MB | 4 MB |
| `unusual_volume` | 41d | 14k | 47 MB | 10 MB |
| `down_30d` | 55d | 19k | 62 MB | 13 MB |
| `below_dma200` | 306d | 103k | 347 MB | 71 MB |
| **concurrent total** | | | **477 MB** | **98 MB** |

477 MB of transient allocation plus process overhead against a 512 MB cap
— one homepage render could exhaust the instance.

**Fixes (two commits, in this order):**
- `ff7ef33` — `select()` the 9 columns `Bar` needs instead of whole
  entities; stream with `yield_per` instead of buffering; drain each
  asset's raw list as it is adjusted so the raw and adjusted universes are
  never both resident. **3.45 -> 0.71 KB/bar, 4.8x.** Verified
  byte-identical output against the old implementation across all 260
  assets / 24,295 bars of the dev universe. Adjustment is untouched.
- `7d4a5cd` — homepage boards swap `below_dma200` (306d) for
  `below_dma50` (84d), taking the four to ~46 MB. Margin, not a second
  fix: at ~98 MB there was no room for a concurrent second visitor.
  `below_dma200` is still reachable from `/opportunities`.

**This is probably the real cause of §8.4's Google failure too.** A
visitor loads the homepage -> the box is OOM-killed -> they click
"Continue with Google" -> the callback hits a dead or restarting backend
-> `error=google`. It fits every probe in §8.4: the OAuth config checked
out because nothing was ever wrong with it. §8.4's `maxDuration` fix is
still correct and worth having, but it would not have fixed this — and a
cold start and an OOM restart both surface as `google_unreachable`, so
that error code does not tell them apart. The Render log does.

- [x] **Confirmed against the Render logs, 2026-09-01.** The Events tab
      (first-party, not inferred) shows 8 kills, all before the fix and
      none after: `"Ran out of memory (used over 512MB) while running your
      code."` at 11:22, 11:37, 11:40 and 11:44 PM Aug 31, then `"Exited
      with status 137"` at 12:47, 12:49, 12:55 and 12:58 AM Sep 1. `5ad5f68`
      (this fix) went live at 1:01 AM. Zero failures since.

**Watch for this pattern elsewhere.** Any path that loads ORM rows per bar
over the universe has the same profile. `alerts.py` uses `WEEK52_BARS`
(252 -> 384 days, wider than anything on the homepage) but is scoped to
watchlisted assets; `screener.py` goes through the same fixed loader.

### 8.7 DB connection pool was too small — fixed 2026-09-01

Found while reading the §8.6 logs for the OOM confirmation above: a
separate, unrelated failure a few minutes after the fix deployed. A real
visitor hit `500` on `GET /opportunities?screen=down_5d&industry=
capital-goods` at 01:04:46 AM; the traceback resolved to

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached,
connection timed out, timeout 30.00
```

`app/db/session.py` never set `pool_size`/`max_overflow`, so SQLAlchemy's
defaults applied — 5 + 10 = 15 connections for the whole process (Render
runs one uvicorn worker, so one engine, one pool). 16 identical timeouts
landed in one 14-second burst (01:04:46-01:05:00 AM) and none since,
searched across the full 2-day log window — a burst, not a sustained leak,
most likely several visitors' concurrent requests (the homepage alone
opens 4) landing right as the new instance's pool was still cold.

**Fix:** `pool_size=10, max_overflow=20` (30 max, up from 15).
`DATABASE_URL` is Neon's pooled endpoint (Deployment.md §1), which fronts
far more capacity than a single free-tier instance will ever open, so this
headroom costs nothing on the database side.

- [ ] Not yet re-verified live — no repeat burst has been observed, but
      the fix hasn't been deliberately load-tested either.

---

## 9. Pending — known data & product gaps

### 9.1 Corporate actions were incomplete — RESOLVED 2026-08-29

The `yfinance_actions` feed **missed bonus issues and demergers**. The
adjustment engine itself was always correct — this was a missing-input bug,
not a wrong-math one. Affected: BAJFINANCE (2025-06-16, 4:1 bonus missing),
ABFRL (2025-05-22 demerger, no action on file at all), VEDL (2026-04-30
demerger), 360ONE (2023-03-02, only a 2× split recorded against a real 4×
move), BAJAJFINSV (2022-09-13, 1:1 bonus missing), SIEMENS (2025-04-07,
Siemens Energy India demerger).

**Fix:** `app/providers/india/nse_actions.py` — NSE's own
`corporates-corporateActions` endpoint, previously believed blocked by
Akamai at the TLS level (`yfinance_actions.py`'s old docstring, verified
live 2026-08-23-or-earlier). Re-verified live 2026-08-29 with the same
`httpx.Client` this codebase actually uses: the homepage still 403s, but
the JSON API answers 200 directly, no cookie priming needed. Now the
primary source (`app/services/corporate_actions.py`), yfinance stays as
fallback. A conservative subject-line classifier only ever types a row
`"split"`/`"bonus"` (the two types `adjustment.py` actually price-adjusts)
when a concrete ratio parses unambiguously; a demerger/rights/unparseable
row is recorded under a type that's deliberately left unadjusted but now
*visible* — `HistoricalEventsPanel`'s existing suspect-action flag had
nothing to flag before this, because these rows didn't exist at all.

Live-verified against the reachable dev database (not just mocks): the new
`python -m app.jobs.backfill_corporate_actions` ingested 1,080 rows across
301 assets, including 33 bonuses, 12 demergers and 22 rights issues yfinance
had never recorded for any of them (HINDUNILVR's demerger, PATANJALI's 3:1
bonus, LALPATHLAB's 2:1 bonus among them). The daily job now also refreshes
a rolling ~13-month window unconditionally (one bulk HTTP call for the
whole market, not 500), which incidentally fixed a second latent bug: the
old per-asset lazy path only ever fetched once per asset, so a genuinely
new action for an already-seeded asset was never caught by anything.

**Resolved 2026-08-31:** `backfill_corporate_actions` has now been run
against the podman prod stack (500 companies, 5 years). 3,825 rows ingested,
138 newly created — the prod DB now carries 81 bonuses, 25 rights and 18
demergers `nse_actions` supplied that yfinance never had. Spot-checked:
BAJFINANCE (2025-06-16 5:1 bonus + 1:2 split), BAJAJFINSV (2022-09-13 1:1
bonus + 1:5 split), ABFRL and SIEMENS demergers all present, and the
adjusted price series is now smooth across each ex-date (BAJFINANCE
2025-06-13→06-16 is +0.5%, not the pre-fix ≈−80% artifact). Adjustment is
applied at read time, so charts/technicals/historical-events were corrected
immediately; stored `score` snapshots refresh on the next `daily_ingestion`.
**A hosted deploy still needs this run once** against its own fresh DB —
Deployment.md §1 step 7.

### 9.2 Fundamentals are single-source and shallow

One provider (yfinance), always rendered at low confidence, fields omitted
rather than estimated. This was flagged as the project's #1 risk from day one
and remains true. An XBRL parser is the real fix.

**Feasibility checked live 2026-08-29** (`API_Sources.md` §7.1): NSE's XBRL
filing endpoint is reachable and a real filing parses cleanly — the
believed-hard part isn't actually the blocker. What makes it real P2 work
rather than a quick add: no bulk discovery (one request per symbol), older
filings have no XBRL at all (HTML-only fallback needed), multiple taxonomy
variants (Ind-AS/non-Ind-AS, standalone/consolidated), and — the reason this
wasn't attempted in the same pass as the other fixes this session —
mismapping a tag would silently produce a *confidently wrong*
`confidence="high"` number, worse than today's honest low-confidence gap.
Needs its own pass with manual cross-checking against real published
results built into the process, not a rushed unsupervised build.

### 9.3 News is one month deep and unclassified

~1 month of history and **every `event_type` is NULL**. Coverage was 24 of
500 assets until the nightly refresh landed (2026-08-28) — news is now
pre-fetched for followed assets plus whatever the `down_*`/`unusual_volume`
screens surface, ~96 assets a night against a 150 cap. The rest stay
lazy-fetched on page view, which is deliberate: all 500 nightly would be
hundreds of Google News calls for stocks nobody opens. Consequences: the historical engine can compare only
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

The gap this used to leave — **peer-percentile normalization** (§X.4) — is
closed as of 2026-08-29: the fundamental components now rank against
same-industry peers when at least 3 have stored data, falling back to the
old absolute bands otherwise. See `Build_plan.md` §X.4 for the design and
`app/services/scoring.py`/`app/engines/scoring/percentile.py` for the code.

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

1. ~~Fix the Gemini key~~ — **done, two bugs, both 2026-08-30**, see §8.2.
2. ~~Fix corporate actions~~ — **done 2026-08-29**; backfill **run against the
   podman prod stack 2026-08-31**, see §9.1. A hosted deploy still needs
   `python -m app.jobs.backfill_corporate_actions` once against its fresh DB
   (Deployment.md §1 step 7).
3. ~~Add a rate limiter~~ — **done**, see §8.3.
4. ~~Peer-percentile normalization~~ — **done 2026-08-29**, see §9.4/§X.4.
5. ~~NL research assistant~~ — **done 2026-08-30**, see `Build_plan.md` §X.8.
6. **→ DEPLOY PUBLICLY (§8.1, §11.3).** This is the only remaining item that
   blocks a real launch, and the only one that needs a human: it is account
   creation (Neon/Render/Vercel) plus DNS, not code.
7. **Re-run the security audit (§8.3)** — launched but aborted on a usage
   limit; it produced no findings *and no assurance*.
8. **Score backtesting (step 26)** — deliberately deferred. Checked
   2026-08-29: the `score` table held only 5 distinct daily snapshots, far
   too little for a score-vs-forward-return correlation to mean anything.
   This is a "wait for the daily job to accumulate history", not a blocker.
9. **Upstox intraday/WebSocket (step 27)** — needs live Upstox API access.

---

## 11. Handover — where we are right now

*Written 2026-08-31 to hand this project to a fresh conversation. If you are
picking this up cold, read this section and §8.1, then start at §11.3.*

### 11.1 What shipped in the last two days

Eleven commits, all on `main`, all pushed, working tree clean:

| Commit | What |
|---|---|
| `a0881fa` | Rate limiter (token bucket, global backstop + per-route ceilings) |
| `b49d25a` | SEBI + AI-generated disclaimers across footer, panels, emails |
| `048684c` | **Corporate-actions data gap fixed** — NSE is reachable after all; now the primary source, yfinance the fallback |
| `f0a931a` | Docs caught up with the above |
| `5422c54` | **Peer-percentile normalization** (§X.4) — the last documented scoring gap |
| `9c34ddb` | XBRL fundamentals feasibility research (reachable; deliberately not built — see §9.2) |
| `893eb83` | **Gemini bug 1** — auth must be an `x-goog-api-key` header, not `?key=` |
| `6fef025` | **Gemini bug 2** — `gemini-flash-latest` was genuinely overloaded; switched to `gemini-flash-lite-latest` + multi-key/multi-model fallback |
| `5d9d4fe` | **NL Research Assistant** (step 25) — 13 read-only tools, native function calling |
| `1a28f4a` | Labeled qualitative general knowledge + company-page "Ask about X" panel |
| `998789f` | Rupee amounts in Indian convention (lakh/crore), never million/billion/trillion |

### 11.2 Things a fresh conversation will otherwise get wrong

- **"Verified working live" in this doc is only as good as the check behind
  it.** Google sign-in was recorded as verified on 2026-08-31 and was
  actually broken (§8.4). The check that passed was a sign-in with an
  already-linked account on a warm dyno; the path that failed was a new
  signup on a cold one. When recording something as verified, record *which
  path* was exercised — "Google sign-in works" hid a failing branch for a day.
- **Vercel route handlers need `maxDuration` too, not just pages.** Anything
  under `frontend/app/api/` that calls the backend blocks on a Render free
  dyno that cold-starts 20-45s, against a ~10s platform default. All ten
  auth handlers now set it; **a newly added route handler will not** unless
  you remember to.
- **The Gemini saga was TWO separate bugs**, and the first fix was real but
  insufficient. Both are documented at length in
  `app/providers/ai/gemini_summary.py`'s module docstring. If AI generation
  breaks again, read that docstring *before* re-diagnosing — it has the exact
  two-command test that tells the failure modes apart.
- **`GEMINI_API_KEY` no longer exists.** It is `GEMINI_API_KEY_1` … `_4`, a
  fallback pool (only `_1` required). Two keys, from two separate Google
  accounts, are currently configured in `backend/.env` and the root `.env`.
- **Live web search is blocked on billing, not on code.** Gemini's
  `google_search` grounding tool (a) cannot be combined with this app's own
  custom function-declaration tools in one request — a documented Gemini API
  constraint — and (b) returned an immediate `429 RESOURCE_EXHAUSTED` on both
  configured accounts, because grounding requires a linked Google Cloud
  **billing account** to get any quota at all. Revisit only if the user sets
  up billing; it would need its own second, search-only call path.
- **Vertex AI was considered and rejected**: no standing free tier, requires
  billing. Contradicts the project's zero-budget constraint.
- **The research assistant may use general knowledge, but only labeled and
  only qualitatively.** Numbers must always come from a tool. This was an
  explicit user decision after the tension was flagged — don't "fix" it back
  to strictly-grounded, and don't loosen it to unlabeled either.
- **`Secrets/` on disk holds real credentials.** It is gitignored. Never
  stage, commit, or print its contents.
- **Podman VM sleep stops every container** (§9.6). If the DB is suddenly
  unreachable, that is almost always the cause — `podman compose -f
  docker-compose.prod.yml up -d`, not a code bug.

### 11.3 Deploying to marketlensai.in — DONE 2026-08-31

**This whole checklist is complete.** It's kept for reference; the actual
step-by-step log with every quirk hit is in `DEPLOY_STATUS.md`, and the
resulting live setup is the table in §8.1. If you're picking this up to
*continue*, read §11.6, not this list.

Full runbook in `Deployment.md`; the order that mattered: (historical)

1. **Database** — create a Neon or Supabase project, hand over the connection
   string. Everything after "here is a connection string" is a coding task:
   convert to `postgresql+psycopg://…?sslmode=require`, run
   `alembic upgrade head`, then seed: `python -m app.services.universe` →
   `python -m app.jobs.backfill_history --days 365` →
   `python -m app.jobs.backfill_corporate_actions` → `python -m
   app.jobs.daily_ingestion`. (The backfill is proven against the podman
   prod stack; a fresh hosted DB still needs its own run — §9.1.)
2. **Backend** — Render or Fly, root `backend`, health check
   `/api/v1/health`. Set every var in §5.3 plus `ENABLE_SCHEDULER=true` and
   **`TRUST_FORWARDED_FOR=true`** (§8.3 — get this wrong and every visitor
   shares one rate-limit bucket).
3. **Frontend** — Vercel, root `frontend`, `API_BASE_URL` = backend URL +
   `/api/v1`. Confirm it works on the `*.vercel.app` URL *before* touching DNS.
4. **DNS (GoDaddy)** — delete the auto-created "Parked" A record on `@` and
   any `AAAA` on `@`, then add A `@` → `76.76.21.21` and CNAME `www` →
   `cname.vercel-dns.com`.
5. **Wire the origins** — set backend `CORS_ORIGINS=https://marketlensai.in`,
   and add `https://marketlensai.in/api/auth/google/callback` to the Google
   OAuth client *and* to `GOOGLE_REDIRECT_URI` (byte-identical).
6. **Email** — add `marketlensai.in` in Resend, paste its MX/SPF/DKIM records
   into GoDaddy, then point `RESEND_FROM_EMAIL` at an address on the verified
   domain. Until this is done Resend only delivers to the account owner, so
   **no real user can complete signup** (§8.2).
7. **Smoke test** — `Deployment.md` §7.

### 11.4 Verified working as of 2026-08-31

Backend gates (`ruff`, `mypy app` — 109 files, 943 tests) all green; frontend
`lint`, `tsc --noEmit`, `build` all green; the full live check table in §8.3
passed. Both containers were rebuilt from the latest commit and confirmed
serving.

### 11.5 Full re-verification pass, 2026-08-31

A second pass the same day, from the handover doc outward:

- **Build vs. plan** — every §S / §4 item accounted for in code: 46 route
  handlers, all 7 engine packages, all 14 providers, 24 tables, 16
  migrations, all 14 frontend pages build. Steps 26 (backtesting) and 27
  (Upstox WS) are the only gaps, both deliberate.
- **Gates** — `ruff` clean, `mypy` clean (109 files), `alembic upgrade head`
  clean, **943 pytest passed** (~2.5 min); frontend `lint` / `tsc` / `build`
  clean. *(A first `pytest` run showed mass failures — the dev Postgres
  container was stopped; bare-metal tests hit `localhost:5432` directly.
  Started it, migrated, re-ran → all green.)*
- **Runtime, against the podman prod stack** — `/health` + every public
  endpoint 200; **live quotes** (`yfinance_quotes`) return real-time data;
  **AI company summary** generated live (WIPRO, grounded); **NL research
  assistant** answered a multi-tool question end-to-end (4 tool calls, real
  computed numbers) and correctly reported an empty account for the
  user-scoped tools; all 14 pages 200; company page renders the candlestick
  chart with DMA overlays, volume, and corporate-action markers; scheduler
  armed (`daily_ingestion scheduled for 20:00 Asia/Kolkata`).
- **Security spot-check on the newest code** — `research_assistant.py` tool
  dispatch can't be steered into overriding `db`/`user` (kwarg collision →
  `TypeError`, caught); all four user-scoped tools filter by `user.id` at the
  service layer; `/assistant/ask` bounds input (2000 / 32 chars), gates on
  `get_current_verified_user`, rate-limited 10/day. No secrets in any tracked
  file; none in the built image. **The full multi-surface audit (§8.3) is
  still not done** — this was the new code only.
- **Fixes applied this pass** — corporate-actions backfill run against the
  prod stack (§9.1); `3100`→`3000` port drift corrected across compose
  comments, `config.py`, `google_oauth.py`, and these docs; required env
  vars (`JWT_SECRET` etc.) added to Deployment.md §2; `render.yaml`,
  `backend/fly.toml`, `frontend/vercel.json` written; empty
  `backend/db_dump.sql` untracked and gitignored.

**Still open before public launch:** the §8.3 security audit; a verified
Resend domain (§8.2); the deploy itself (§8.1).

### 11.6 Deployed — continue here (2026-08-31, late)

The whole thing shipped in one long session. **Live at
<https://marketlensai.in>.** Hosting map is the §8.1 table; the step log
with every quirk (GoDaddy WHOIS hold, Website Builder site blocking the DNS
record, Vercel monorepo detection, `output:"standalone"` breaking Vercel's
build, the ai-summary test needing a Gemini-key stub in CI) is in
`DEPLOY_STATUS.md`.

**What a fresh session must know:**

- **Two git remotes, push to both.** `origin` = safiyat/ronrack (the
  original), `mine` = ronitk2803-ai/MarketLensAI (what Render + Vercel
  deploy from). `git push origin main && git push mine main` after every
  commit, or the live site won't update.
- **Commits made this session** (all on both remotes): `6eeb376` deploy
  configs + doc fixes, `341f945` corp-action dedup crash fix, `f20ed19`
  free-tier wiring + nightly workflow, `8693763` + `b705514` Vercel build
  fixes, `52ae0da` CI test fix, then the `maxDuration=60` frontend commit,
  plus several `DEPLOY_STATUS.md` progress commits.
- **Verified working live on marketlensai.in:** market overview, company
  pages (chart + score). CI green, nightly ingestion green. **Google
  sign-in was recorded here as verified and was not** — it failed with
  `/login?error=google` on 2026-09-01. See §8.4; the lesson is in §11.2.
- **Post-deploy cleanup, done 2026-08-31:** the `Deployment.md` §7 smoke
  test has been run against the live site (register → verify email →
  watchlist write → screener → research assistant); the cron-job.org
  keep-alive ping is now every 5 min, not 10; the Neon password has been
  reset.
- **Known rough edges** (none block use): the Render free dyno still
  cold-starts 20-45s on the first hit after a genuinely idle stretch; if that
  stays annoying the fix is Render Starter (~$7/mo). Consider re-adding
  `www.`.
- **Still genuinely pending** (pre-existing, not deploy work): the §8.3
  security audit; XBRL fundamentals (§9.2); score backtesting (step 26);
  Upstox intraday (step 27).
- **When the dust settles:** fold §8.1 + this section into the doc body,
  update §S/§4, and delete `DEPLOY_STATUS.md`.
