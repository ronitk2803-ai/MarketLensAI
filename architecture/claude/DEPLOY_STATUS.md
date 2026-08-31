# DEPLOY STATUS — live progress of the marketlensai.in deployment

> Working notes for the in-progress first deployment (started 2026-08-31).
> Full reference: `Deployment.md`. Status + architecture: `SUMMARISER.md`.
> When the deploy is finished, fold anything durable into those two and
> delete this file.

## Decisions made

| Thing | Choice | Why |
|---|---|---|
| Database | **Neon** free tier, region **AWS ap-southeast-1 (Singapore)**, Postgres 17, Neon Auth OFF | Simplest connection string; closest region to India; app has its own auth |
| Backend host | **Render** free plan, Singapore | Zero budget. Tradeoff: sleeps after 15 min idle, ~50s cold start |
| Nightly job | **GitHub Actions cron** (`.github/workflows/nightly-ingestion.yml`) | Render free sleeps, so an in-process scheduler would miss runs |
| Frontend | **Vercel** Hobby (free) | Standard for Next.js |
| `ENABLE_SCHEDULER` | `false` on Render | see above |

## Done

- [x] Neon project created, region Singapore, PG17
- [x] `alembic upgrade head` against Neon — schema at `3c29bc20a54b`
- [x] `python -m app.services.universe` — 500 companies, 20 industries
- [x] `python -m app.jobs.backfill_history --days 450` — 150,160 bars, 305 trading days
- [x] `python -m app.jobs.backfill_corporate_actions` — 3,825 rows
- [x] Bug found + fixed mid-seed: `ingest_corporate_actions` duplicate-row crash (commit `341f945`)
- [x] `python -m app.jobs.daily_ingestion` — 500 scores, 0 errors; corp-action fix confirmed
- [x] **Step 3 — backend live** at https://mlai-backend.onrender.com (Render free, Docker).
      `/api/v1/health` + `/opportunities/screens` verified serving from Neon.
- [x] **Step 4 — frontend live** at https://market-lens-ai-phi.vercel.app (Vercel Hobby,
      team "MLAI", project `market-lens-ai`, root dir `frontend`, `API_BASE_URL` set).
      Two build fixes were needed: `vercel.json` had a `regions` pin (Hobby rejects it,
      commit 8693763) and `next.config.ts` `output: "standalone"` broke Vercel's build
      (now conditional on `!process.env.VERCEL`, commit b705514).
- [x] **Keep-alive**: cron-job.org pings `/api/v1/health` every 10 min so Render doesn't
      sleep (its 50s cold start exceeds Vercel's 10s fetch timeout → "Couldn't load market
      data"). Confirmed: site works when backend is warm.

## Remaining: Steps 5-9

- [x] **Step 5 — DNS DONE.** GoDaddy hold lifted (WHOIS verified), Website Builder draft
      deleted, `A @ 216.198.79.1` set. https://marketlensai.in is LIVE with valid TLS,
      market overview + company pages rendering. Still to wire (quick):
      - Render `CORS_ORIGINS` = `https://marketlensai.in` — confirm it's set
      - Google Cloud Console -> OAuth client -> add redirect URI
        `https://marketlensai.in/api/auth/google/callback`
      - (`noreply@marketlensai.in` mailbox created in GoDaddy for Step 6)

<details><summary>Step 5 history (blocked, now resolved)</summary>
      - Vercel: `marketlensai.in` added, apex-only (no www — a www entry was deleted
        during setup; re-add later if wanted), connected to Production, shows
        "Invalid Configuration" pending DNS. `market-lens-ai-phi.vercel.app` is valid.
      - Vercel wants ONE record: `A` `@` -> **216.198.79.1** (new Vercel IP; legacy
        76.76.21.21 also works). Shown under the domain's "View DNS configuration".
      - **BLOCKER (escalated):** the domain is now on a GoDaddy **"status hold"** —
        it won't resolve at all until lifted. Almost certainly ICANN registrant-email
        verification not completed (pending -> hold). Fix: open the actual GoDaddy
        verification email to ronit.k2803@gmail.com (check spam) and click its link;
        the dashboard "Validate" button just resends it. If already verified and still
        held, contact GoDaddy support. Until the hold lifts, DNS changes are pointless.
      - Also still true once the hold lifts: the `A @` record is held by a GoDaddy
        Website Builder DRAFT site ("Market Lens AI"). Delete it at
        websites.godaddy.com -> site -> Settings -> Delete Site, then set
        `A @` -> 216.198.79.1.
      - GoDaddy already has `CNAME www -> marketlensai.in.` (fine, leave it). Leave NS,
        SOA, `_dmarc` TXT, `_domainconnect` alone.
      - AFTER DNS is green: Render env `CORS_ORIGINS` is already `https://marketlensai.in`
        (confirm); add `https://marketlensai.in/api/auth/google/callback` to the Google
        OAuth client in Google Cloud Console and confirm Render's `GOOGLE_REDIRECT_URI`
        matches byte-for-byte.

</details>

- [ ] **Step 6 — Resend domain.** resend.com/domains → add marketlensai.in → paste
      MX/SPF/DKIM into GoDaddy → set Render `RESEND_FROM_EMAIL=MarketLens AI <noreply@marketlensai.in>`.
      Until done, only the Resend account owner gets verification/reset email.
- [ ] **Step 7 — GitHub Actions nightly.** Repo Settings → Secrets and variables → Actions:
      add `DATABASE_URL` (the +psycopg Neon string) and `JWT_SECRET` (any value). Then
      Actions tab → "Nightly ingestion" → Run workflow once to confirm.
      NOTE: the workflow file is on `mine/main` (ronitk2803-ai/MarketLensAI) — add the
      secrets on THAT repo.
- [ ] **Step 8 — smoke test** (Deployment.md §7).
- [ ] **Step 9 — reset Neon password** (pasted in chat), update Render `DATABASE_URL` +
      the GitHub `DATABASE_URL` secret. Then fold this file into SUMMARISER.md §11 and delete it.

## IMPORTANT: deploy repo changed

Render (and Vercel) deploy from **`ronitk2803-ai/MarketLensAI`**, not
`safiyat/ronrack` — the user's Render/GitHub account had no access to
`safiyat/ronrack`. Local repo now has two remotes:
`origin` = safiyat/ronrack, `mine` = ronitk2803-ai/MarketLensAI.
**Push future changes to BOTH:** `git push origin main && git push mine main`
(Render auto-deploys on push to `mine`).

Render env vars were NOT prompted by the Blueprint — they were added by hand
on the service's Environment tab (DATABASE_URL, CORS_ORIGINS, GEMINI_API_KEY_1/2,
RESEND_API_KEY, GOOGLE_CLIENT_ID/SECRET, GOOGLE_REDIRECT_URI). JWT_SECRET/ENV/
ENABLE_SCHEDULER/TRUST_FORWARDED_FOR came from the blueprint.

The Neon connection string (with password) lives only on the developer's
machine, exported as `DATABASE_URL` in the seeding terminal. It was pasted
once into chat unmasked — **reset the Neon `neondb_owner` password once the
deploy is done** and update it in Render + GitHub secrets.

## Remaining steps

### Step 3 — Deploy the backend to Render

1. Push any pending commits first (see bottom of this file).
2. render.com → sign up with GitHub → **New → Blueprint** → pick the `ronrack` repo.
3. Render reads `render.yaml` and shows one service `mlai-backend` with a few
   env vars to fill (`sync: false` ones). Enter:
   - `DATABASE_URL` = the Neon string, but change the scheme from
     `postgresql://` to `postgresql+psycopg://` (leave `?sslmode=require&channel_binding=require`)
   - `CORS_ORIGINS` = `https://marketlensai.in` (add the Vercel preview URL later too if needed)
   - `GEMINI_API_KEY_1` and `GEMINI_API_KEY_2` = from `backend/.env` on the dev machine
   - `RESEND_API_KEY` = from `backend/.env`
   - `RESEND_FROM_EMAIL` = leave blank for now (defaults to `onboarding@resend.dev`; fix in Step 6)
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` = from `backend/.env`
   - `GOOGLE_REDIRECT_URI` = `https://marketlensai.in/api/auth/google/callback`
   - `GEMINI_API_KEY_3`, `GEMINI_API_KEY_4`, `UPSTOX_*`, `ADMIN_TOKEN` = leave blank
   - `JWT_SECRET` is auto-generated by Render — don't touch it
4. **Apply / Create**. Watch the deploy log: it builds `backend/Dockerfile`,
   runs `alembic upgrade head` (should report nothing pending — already done),
   then `uvicorn` starts.
5. If the Blueprint refuses the free plan: create it manually instead
   (New → Web Service → the repo → root dir `backend`, Docker auto-detected,
   health check path `/api/v1/health`, plan Free) and set every env var from
   the table in `Deployment.md` §2 by hand.
6. Test: open `https://<your-service>.onrender.com/api/v1/health` → `{"status":"ok"}`
   (first hit may take ~50s while it wakes). Also try
   `https://<your-service>.onrender.com/api/v1/opportunities/screens` → JSON list.
7. **Copy the `onrender.com` URL** — needed in Step 4.

### Step 4 — Deploy the frontend to Vercel

1. vercel.com → sign up with GitHub → **Add New → Project** → import `ronrack`.
2. **Root Directory: `frontend`** (click Edit, select the folder). Framework
   auto-detects as Next.js. `frontend/vercel.json` handles the rest.
3. Environment variable: `API_BASE_URL` = `https://<your-render-service>.onrender.com/api/v1`
   (the Render URL from Step 3.7 + `/api/v1`).
4. **Deploy.** When it finishes you get a `https://<project>.vercel.app` URL.
5. Test that URL directly in a browser — the market overview page should load
   with data (first load slow if Render is asleep). Click into a company page,
   check the price chart renders.
6. If pages error: check the Render `CORS_ORIGINS` includes the `.vercel.app`
   URL, or just wait for Step 5 (custom domain) and add only that.

### Step 5 — Point marketlensai.in at Vercel + wire origins

1. In Vercel: Project → **Settings → Domains** → add `marketlensai.in` and
   `www.marketlensai.in`. Vercel shows the DNS records to create.
2. In GoDaddy → `marketlensai.in` → **DNS**:
   - **Delete** the default parked `A` record on `@` and any `AAAA` on `@` and
     the default `CNAME www`.
   - Add `A` `@` → `76.76.21.21`
   - Add `CNAME` `www` → `cname.vercel-dns.com`
   - (Use exactly what Vercel's Domains page tells you if it differs.)
3. Wait for DNS (minutes to a few hours). Vercel's Domains page flips to
   "Valid Configuration" and issues TLS automatically.
4. In Render → `mlai-backend` → Environment: confirm
   `CORS_ORIGINS = https://marketlensai.in` (no `www`, no trailing slash;
   add `,https://www.marketlensai.in` if you want www to work as an origin).
   Save → it redeploys.
5. Google Cloud Console → APIs & Services → Credentials → the OAuth client →
   add `https://marketlensai.in/api/auth/google/callback` to **Authorized
   redirect URIs**. Confirm Render's `GOOGLE_REDIRECT_URI` matches it byte for byte.

### Step 6 — Resend domain (so real users can get email)

Until this is done, verification + password-reset emails only reach the
Resend account owner's own address. Everyone else's signup silently fails.

1. resend.com → **Domains** → Add Domain → `marketlensai.in`.
2. Paste the MX / TXT (SPF) / TXT (DKIM) records it gives you into GoDaddy DNS.
3. Wait for Resend to show the domain "Verified".
4. Render → `mlai-backend` → Environment → set
   `RESEND_FROM_EMAIL` = `MarketLens AI <noreply@marketlensai.in>` → save (redeploys).

### Step 7 — GitHub Actions nightly job

1. GitHub → the `ronrack` repo → **Settings → Secrets and variables → Actions
   → New repository secret**, twice:
   - `DATABASE_URL` = the same `postgresql+psycopg://…` Neon string
   - `JWT_SECRET` = any string (e.g. run `python3 -c "import secrets;print(secrets.token_urlsafe(48))"`)
2. **Actions** tab → "Nightly ingestion" workflow → **Run workflow** (manual
   trigger) to confirm it works. It should finish green in ~20-30 min.
3. After that it runs itself every day at 14:30 UTC / 20:00 IST.

### Step 8 — Smoke test (Deployment.md §7)

- [ ] `https://marketlensai.in` loads the market overview with data
- [ ] a company page shows a price chart + score + technicals
- [ ] `/opportunities` shows screens with hits
- [ ] browser devtools → Network → no CORS errors
- [ ] register a test account → verification email arrives (to your own
      address at least) → verified write works
- [ ] `https://marketlensai.in/research` → ask a question → grounded answer
- [ ] backend `/api/v1/health` returns 200

### Step 9 — Clean up

- [ ] Reset the Neon `neondb_owner` password; update `DATABASE_URL` in Render
      env and the GitHub `DATABASE_URL` secret
- [ ] Fold this file's outcome into `SUMMARISER.md` §11 and delete this file
- [ ] Optional: a free uptime pinger (cron-job.org) hitting
      `https://<render-url>/api/v1/health` every 10 min keeps the API warm so
      visitors don't hit the ~50s cold start

## Pending commits at last session end

`render.yaml` (switched to free plan + scheduler off),
`.github/workflows/nightly-ingestion.yml` (new), this file. Should be on
`main` as of commit after `341f945`.
