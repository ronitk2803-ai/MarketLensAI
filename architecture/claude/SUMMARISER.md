# SUMMARISER — Project Onboarding & Overview (`mlai`)

> **Read this first.** One-page (ish) orientation for anyone joining the project. It explains *what* we're building, *why*, *how*, and *where to find the details*. Codename **`mlai`** is a placeholder — the real brand is not finalized, so nothing is hard-coded to a name.

---

## 1. The one-liner
An **AI-powered investment intelligence platform** for Indian equities (Nifty 500 first) that helps investors **discover opportunities and build *or challenge* their conviction** using multiple sources of evidence in one place — starting from **data**, moving to **information → context → insight → opportunity**.

It is **not** a buy/sell tipping service and **not** just another screener.

## 2. The problem we solve
Investors juggle many fragmented tools — charts, financials, ratios, news, screeners, sentiment — and must connect the dots themselves. When a stock drops 25%, a normal screener just says "-25%." We answer the real question: **why did it fall, and does it deserve research?** (genuine deterioration vs temporary overreaction). Inspired by real cases like Paytm's 2024 fall and Ola Electric's multi-arm thesis.

## 3. Core philosophy (non-negotiable)
- **Explain, don't recommend.** AI never says just "BUY/SELL/HOLD." It presents *what happened, why, what changed, bull/bear cases, risks, supporting & contradicting evidence, what to monitor, and confidence.*
- **Evidence over opinion.** Facts are clearly separated from AI interpretation. **Never present speculation as fact; never fabricate data.**
- **The user is the final decision-maker.** We help build or challenge conviction — we don't decide.
- **Positioning:** investment *research/education*, not regulated advice. No "guaranteed"/"risk-free"/"will go up" language.

## 4. What makes it different
1. **Opportunity Discovery** — not just "tell me about this stock" but "*what deserves my attention?*" (e.g. Nifty 500 stocks down sharply that still have intact fundamentals).
2. **Contextual analysis** — connects price, fundamentals, valuation, news, volume, and history to explain moves.
3. **Historical event/recovery engine** — "has this happened before, and what happened after?" (context, never a prediction).
4. **Thesis Tracker** — you write a thesis + the conditions that would *invalidate* it; the platform watches those conditions and flags when your thesis is challenged.
5. **Industry-specific scoring** — banking, IT, manufacturing each judged on metrics that actually matter for them.

## 5. Feature list (by priority)
**P0 — MVP (public, read-only, ~1 week target):**
- Stock universe (Nifty 500) + search
- Company page: header, adjusted candlestick chart (with split/bonus markers), performance, technical indicators, best-effort fundamentals (flagged where missing), news
- **Opportunity Finder** (screens: sharp falls, below DMAs, unusual volume, relative strength, etc.) with attention ranking
- **Opportunity Score** with a per-component breakdown (labeled "research attractiveness," never a return prediction)

**P1:** authentication • portfolio (incl. Zerodha CSV import) • watchlist • AI single-company analysis (grounded + cited) • **Thesis Tracker**

**P2:** historical event/recovery engine • advanced combinable screener • full industry-specific scoring • intelligent alerts • natural-language research assistant • score backtesting

## 6. How it works (architecture in brief)
```
Next.js (frontend)  →  FastAPI (backend)  →  Application services
                                                   ↓
                              Engines (pure calc)  |  Providers (all external IO)
                                                   ↓
                                        PostgreSQL / cache
```
- **Engines** (indicators, opportunity, scoring, thesis) are pure and testable — no network.
- **Providers** are the only place external APIs are called, hidden behind interfaces so any source can be swapped without a rewrite.
- **AI** only reasons over data we already hold, with citations — it never invents numbers or fetches raw data.
- **Market-agnostic core:** India is data, not code — so US equities / MFs / ETFs / crypto can be added later.

## 7. Data strategy in brief
- **Free-first.** Budget ~₹0. Paid feeds added later only when a gap justifies it (₹500/mo does *not* buy quality Indian fundamentals; the real fix is ~₹1,700–5,000/mo — see `API_Sources.md`).
- **Prices:** Upstox (preferred, free broker API) + **NSE Bhavcopy** (auth-free EOD spine + delivery %) + Angel/Fyers/Dhan fallbacks + yfinance backfill. Two-source reconciliation for correctness.
- **Own database** holds **full daily history (OHLCV + delivery %)**; today's live prices come from Upstox. Charts are corporate-action-adjusted with visible split/bonus markers.
- **Fundamentals = the hard part:** partial + explicitly flagged, never fabricated; curated Nifty 500 seed for MVP; XBRL parser later.
- **News:** RSS + NSE/BSE announcements + GDELT + entity/sentiment enrichers, deduped.
- Every datapoint carries **`source` + `as_of` + `confidence`**.

## 8. Tech stack
Next.js + TypeScript + Tailwind/shadcn (frontend) • FastAPI + Python 3.12 (backend) • PostgreSQL (Supabase/Neon) • SQLAlchemy + Alembic • APScheduler jobs • provider-abstracted LLM for AI. Free-tier hosting (Vercel + Render/Fly + Neon/Supabase).

## 9. Key decisions already made
See [`docs/decision_log.md`](docs/decision_log.md). Highlights: Upstox-primary + Bhavcopy spine; store full history; adjusted candlesticks with markers; fundamentals partial+flagged; free-first; no auth in P0.

## 10. Open decisions before coding
See `Build_plan.md` §V. Top three: **fundamentals source for MVP**, **DB/host (Supabase vs Neon)**, **Upstox daily-token strategy**.

## 11. Where to find what (doc map)
| Doc | Purpose |
|---|---|
| `SUMMARISER.md` (this) | Start-here overview for teammates |
| `Build_plan.md` | The detailed build plan (sections A–X): architecture, schema, engines, sequence, risks, DoD |
| `API_Sources.md` | Every data source per need, with fallbacks, trust tiers, and paid-upgrade options |
| `docs/founder_vision.md` | The "why" and inspiration |
| `docs/product_principles.md` | The rules we build by |
| `docs/architecture.md` | System architecture in depth |
| `docs/data_strategy.md` | Data sourcing, storage, caching, correctness |
| `docs/roadmap.md` | P0/P1/P2 milestones & sequence |
| `docs/decision_log.md` | Irreversible decisions + why |
| `docs/features/` | One spec per feature (as they're built) |

## 12. Current status & how to start
- **Status:** Planning complete. **No application code written yet** (deliberate — docs are the source of truth first).
- **First implementation step:** scaffold the repo (Build_plan.md §S, Step 1), then build feature-by-feature (implement → test → commit → next). Keep prompts short; don't restate the vision — point to these docs.
- **Golden rules for contributors:** never fabricate data; keep providers swappable; keep engines pure; never expose secrets/API keys; use evidence-based language.
