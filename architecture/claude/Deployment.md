# Deployment Runbook (Build_plan.md §S step 15)

Target stack, per Build_plan.md §Q/§S: **Vercel** (frontend) + **Render or
Fly.io** (backend) + **Supabase or Neon** (Postgres) + scheduled daily
ingestion. This doc covers everything after the code is ready: creating
accounts, wiring env vars, running migrations, and confirming it's alive.

Code-side prerequisites (already done, and verified by actually building and
running the image against a throwaway Postgres — migrations from an empty
schema, API serving, admin gate returning 401, CORS honouring only the
configured origin, both scheduling modes, and both CLI entrypoints):
- [backend/Dockerfile](../../backend/Dockerfile) — multi-stage `uv` build, runs
  `alembic upgrade head` then `uvicorn` on container start. Final image is
  ~217 MB and runs as a non-root `mlai` user; `tests/` and `.env` are
  excluded via `.dockerignore`.
- [backend/app/jobs/daily_ingestion.py](../../backend/app/jobs/daily_ingestion.py)
  — the daily job (prices → corporate actions → scores).
- In-process scheduler wired into [backend/app/main.py](../../backend/app/main.py)'s
  lifespan, gated behind `ENABLE_SCHEDULER` (off by default).

---

## 0. Run the whole thing locally first (no accounts needed)

[docker-compose.prod.yml](../../docker-compose.prod.yml) runs the full
stack — Postgres, backend, frontend — in containers on your own machine.
This is the fastest way to see the real product, and it exercises the same
images the hosted deploy uses.

```bash
podman compose -f docker-compose.prod.yml up -d --build
```

Frontend on <http://localhost:3100>, backend on <http://localhost:8000>.
It is deliberately isolated from the dev `docker-compose.yml`: its own
project name, its own volume, Postgres on 5433 instead of 5432. Bringing it
up will not touch your dev database. (The explicit `name:` in that file is
what guarantees this — without it, compose derives the project name from the
directory, both files collide, and the dev Postgres container gets recreated
against the prod volume.)

Then seed it — a fresh database has no universe and no prices, so every page
is empty until you do:

```bash
podman compose -f docker-compose.prod.yml exec backend python -m app.services.universe
```
```bash
podman compose -f docker-compose.prod.yml exec backend python -m app.jobs.backfill_history --days 365
```

The first defines the universe: it takes NSE's Nifty 500 constituent CSV as
the membership list and Upstox's public instrument dump (no token needed)
for the instrument keys, seeding the 500 members and marking everything else
inactive. Pass `--index all` to seed the full ~2,643-instrument tradable list
instead. The second backfills a year of end-of-day prices from NSE Bhavcopy
in committed monthly chunks. Screens and charts work as soon as it finishes.

Scores are the slow part: each asset needs a live fundamentals fetch at
~2.5s, so the Nifty 500 takes ~20 minutes (the unfiltered universe would be
~1.5 hours — the main reason the filter matters operationally). The nightly
job does this on its own; to populate it immediately, run
`python -m app.jobs.daily_ingestion`. Until scores exist the screener still
works — it ranks scored rows first and shows `–` for the rest, by design.

To tear it down (`-v` also deletes the prod database volume):
```bash
podman compose -f docker-compose.prod.yml down
```

---

## 1. Database — Supabase or Neon

Either works; both give a managed Postgres with a connection string. Pick
whichever account you'd rather have.

1. Create a project (region: pick one close to your backend host — matters
   for query latency, not correctness).
2. Grab the connection string. You want the **direct** (non-pooled) one for
   running Alembic migrations, and — for Supabase specifically — the
   **pooled/transaction-mode (port 6543)** string for the app's normal
   runtime traffic, since a small always-on backend can otherwise exhaust
   Supabase's direct connection limit. Neon's default string is already
   poolable, so this distinction doesn't apply there.
3. Convert it to SQLAlchemy's `psycopg` driver form — the app expects:
   ```
   postgresql+psycopg://<user>:<password>@<host>:<port>/<db>?sslmode=require
   ```
   (Supabase/Neon connection strings are usually handed to you as
   `postgresql://...` — just add the `+psycopg` and `sslmode=require`.)
4. From your machine (with this connection string temporarily in
   `DATABASE_URL`), run migrations once to create the schema:
   ```bash
   cd backend
   DATABASE_URL="postgresql+psycopg://...supabase or neon host.../postgres?sslmode=require" \
     .venv/bin/alembic upgrade head
   ```
   The container also runs `alembic upgrade head` on every start (see
   Dockerfile), so this manual run is really just to confirm the string is
   right before wiring it into the platform — subsequent migrations ship
   automatically on deploy.
5. Seed the universe once against this DB:
   ```bash
   DATABASE_URL="...same string as above..." .venv/bin/python -m app.services.universe
   ```
   Membership comes from NSE's `ind_nifty500list.csv` (API_Sources.md §2's
   designated primary source) and the instrument keys from Upstox's public
   instrument dump; neither needs a token. **Verified live: all 500
   constituents matched against the 2,643-instrument dump, nothing
   unmatched**, and all 500 classify as EQUITY — the index carries no ETFs.

   Assets that are not constituents are marked **inactive rather than
   deleted**, so their price history and stored scores survive a rebalance
   and cost nothing to restore. Search, company pages, and screens all
   filter on `active`, so deactivation removes them from the product
   completely. Pass `--index all` to seed the full tradable list instead.

   Without this step, `/opportunities` and search come back empty. Re-run
   **monthly** per API_Sources.md §2 to track rebalances — it is not part of
   the daily job on purpose (see the docstring in
   [daily_ingestion.py](../../backend/app/jobs/daily_ingestion.py)).
6. Backfill price history, or the charts and every moving-average screen
   start empty and stay that way until enough daily runs accumulate:
   ```bash
   DATABASE_URL="...same string as above..." \
     .venv/bin/python -m app.jobs.backfill_history --days 365
   ```
   Chunked and committed per month on purpose — `backfill_universe_from_
   bhavcopy` holds a whole run in one transaction, which is right for the
   daily 10-day delta and wrong for a year across 2.6k symbols.

---

## 2. Backend — Render or Fly.io

Both build from the `backend/Dockerfile` directly; pick one.

### Render
1. New → Web Service → connect this repo, root directory `backend`.
2. Render auto-detects the Dockerfile. Set the health check path to `/api/v1/health`.
3. Instance type: the free/starter tier is fine for MVP traffic.
4. Environment variables (Render → Environment tab):

   | Key | Value |
   |---|---|
   | `ENV` | `production` |
   | `DATABASE_URL` | the pooled connection string from step 1 |
   | `CORS_ORIGINS` | your Vercel URL, e.g. `https://mlai.vercel.app` |
   | `UPSTOX_API_KEY` | from your Upstox developer app |
   | `UPSTOX_API_SECRET` | from your Upstox developer app |
   | `UPSTOX_REDIRECT_URI` | must exactly match what's registered with Upstox — see §4 |
   | `ADMIN_TOKEN` | any long random string you generate — gates `/admin/*` |
   | `ENABLE_SCHEDULER` | `true` (Render's web service is always-on, so the in-process APScheduler default works — see §5 if you'd rather use Render's own Cron Job feature instead) |
   | `TRUST_FORWARDED_FOR` | `true` — Render sits in front of this container as a real reverse proxy, so `X-Forwarded-For` genuinely reflects the visitor's IP here. This is the one rate-limiter setting (app/core/rate_limit.py) that's platform-dependent rather than optional-with-a-safe-default: get it wrong and every visitor is keyed on Render's own edge IP instead of their own, so they all share one rate-limit bucket. |

5. Deploy. Watch the build logs for the `alembic upgrade head` line on
   container start — it should report no pending revisions (you already
   applied them in step 1) and then uvicorn should come up.
6. Hit `https://<your-render-url>/api/v1/health` — expect
   `{"status": "ok"}`, per
   [test_health.py](../../backend/tests/test_health.py).

### Fly.io (alternative)
```bash
cd backend
fly launch --no-deploy   # generates fly.toml, pick the region/org interactively
fly secrets set DATABASE_URL="..." CORS_ORIGINS="https://mlai.vercel.app" \
  UPSTOX_API_KEY="..." UPSTOX_API_SECRET="..." UPSTOX_REDIRECT_URI="..." \
  ADMIN_TOKEN="..." ENABLE_SCHEDULER="true" TRUST_FORWARDED_FOR="true"
fly deploy
```
Fly builds the same `backend/Dockerfile` — no separate `fly.toml` app
config is needed beyond what `fly launch` generates, since the Dockerfile
already defines the start command.

---

## 3. Frontend — Vercel

1. Import this repo into Vercel, set the project root to `frontend`.
2. Framework preset: Next.js (auto-detected).
3. Environment variable: `API_BASE_URL` = your backend's public URL +
   `/api/v1`, e.g. `https://mlai-backend.onrender.com/api/v1`. This is the
   same variable [frontend/lib/api.ts](../../frontend/lib/api.ts) reads —
   without it the app falls back to `http://localhost:8000/api/v1`, which
   won't resolve in production.
4. Deploy. Vercel builds with `next build` — note that
   [frontend/app/opportunities/page.tsx](../../frontend/app/opportunities/page.tsx)
   and the company page are `force-dynamic` specifically so this build
   doesn't need the backend reachable at build time.
5. Once live, add the Vercel URL to the backend's `CORS_ORIGINS` (§2) if
   you hadn't already — cross-origin fetches will otherwise fail silently
   in the browser console, not as a visible error on the page.

---

## 4. Upstox app registration

Before any of this works end-to-end, register an app at
[Upstox Developer Console](https://developer.upstox.com/) (real URL, not
guessed — go there directly, don't follow a link from anywhere else):
- Redirect URI must be a URL you control and can read the `code` query
  param from — simplest is a URL on your deployed frontend, e.g.
  `https://mlai.vercel.app/upstox-callback` (add a trivial page there that
  just displays the `code` param so you can copy it — see §5).
- Copy the API key/secret into `UPSTOX_API_KEY`/`UPSTOX_API_SECRET`.

---

## 5. Daily Upstox re-authentication (manual, by design)

`UpstoxTokenManager` is deliberately in-memory and never stores your
password/PIN/TOTP — see
[upstox_token_manager.py](../../backend/app/providers/auth/upstox_token_manager.py).
This means **two operational consequences**:

- The access token expires daily around 03:30 IST — Upstox has no refresh
  token. NSE Bhavcopy (auth-free) still covers the EOD price spine on days
  you skip this, so nothing breaks, but Upstox-only data (real-time-ish
  quotes, some corporate action feeds) goes stale until you redo this.
- **A backend restart or redeploy also clears the token** (in-memory, not
  DB-backed) — redo this after every deploy, not just once a day.

To refresh it:
1. Visit `https://api.upstox.com/v2/login/authorization/dialog?client_id=<UPSTOX_API_KEY>&redirect_uri=<UPSTOX_REDIRECT_URI>&response_type=code`
   in your browser and log in with your own Upstox credentials (this
   happens entirely on Upstox's site — this server never sees your
   password/PIN/TOTP).
2. Upstox redirects to your `UPSTOX_REDIRECT_URI` with `?code=...` in the
   URL — copy that code.
3. Redeem it:
   ```bash
   curl -X POST https://<your-backend-url>/api/v1/admin/upstox/token \
     -H "X-Admin-Token: <your ADMIN_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"code": "<the code from step 2>"}'
   ```
   Expect `{"status": "ok"}`.

If you'd rather not do this daily by hand, this is the natural place to
later swap `UpstoxTokenManager` for a DB-backed store and automate the
redirect-capture with a small script — deliberately out of scope for the
MVP per the original refusal to automate credential entry.

---

## 6. Scheduled ingestion — two options

Whichever you pick, confirm it in the logs — application logging is
explicitly configured ([app/core/logging.py](../../backend/app/core/logging.py))
because uvicorn only sets up its own `uvicorn.*` loggers and leaves root at
WARNING, which silently swallowed everything this app logs, including the
job's per-asset error handling. With Option A you should see an
`apscheduler.scheduler Scheduler started` line plus
`daily_ingestion scheduled for 20:00 Asia/Kolkata` at boot; if those are
absent, the scheduler is not running.

**Option A (default, already wired): in-process APScheduler.**
Set `ENABLE_SCHEDULER=true` (done in §2). Runs
`app.jobs.daily_ingestion.run_daily_ingestion` once a day at
`DAILY_INGESTION_HOUR_IST` (default `20`, i.e. 20:00 IST — after Bhavcopy
is typically published). Only correct for a platform that keeps one
instance always running (Render/Fly's default web service does; don't
enable this on something that scales to zero).

**Option B: platform cron trigger.** Leave `ENABLE_SCHEDULER` unset/`false`
and instead configure the platform's own scheduler to run:
```bash
python -m app.jobs.daily_ingestion
```
against the same container image/environment. Render has "Cron Jobs" as a
separate service type; Fly has `fly.toml` `[[ services ]]` — actually Fly's
mechanism is a **Fly Machine scheduled via `fly machine run --schedule`**,
worth checking Fly's current docs since this changes over time.

Use Option B if you outgrow a single always-on instance; Option A is
simpler and is what's on by default.

---

## 7. Smoke-test checklist

After both deploys and one Upstox re-auth (§5):

- [ ] `GET /api/v1/health` on the backend returns 200.
- [ ] Frontend homepage loads, search returns results (confirms DB is
      seeded and reachable).
- [ ] A company page (`/company/<SYMBOL>`) shows a price chart — confirms
      Bhavcopy/Upstox price data reached Postgres.
- [ ] `/opportunities` shows at least one screen with hits (confirms
      scoring ran — may be empty until the first scheduled `daily_ingestion`
      run completes; trigger it manually once via
      `python -m app.jobs.daily_ingestion` against the prod `DATABASE_URL`
      if you don't want to wait for the schedule).
- [ ] Browser devtools network tab shows no CORS errors on any page.
- [ ] `POST /api/v1/admin/upstox/token` without `X-Admin-Token` returns 401
      (confirms the admin gate is live, not just present in code).
- [ ] Backend logs show the scheduler lines from §6 (if using Option A) —
      their absence is the only signal that ingestion silently isn't running.

### Reproducing the container test locally

The whole chain above was validated this way and can be re-run before any
deploy, without touching the dev database:

```bash
podman build -t mlai-backend:test backend
```
Then create a throwaway database, run the container against it with
`DATABASE_URL` pointed at that database, and check `/api/v1/health`, the
migration output, and the two CLI entrypoints
(`python -m app.services.universe`, `python -m app.jobs.daily_ingestion`).
