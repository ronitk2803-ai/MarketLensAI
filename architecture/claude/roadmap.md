# Roadmap — `mlai`

> Priorities and build sequence. Detail in `Build_plan.md` §R/§S. Dates are relative (no fixed calendar committed).

## Milestones

### M0 — Foundation
Repo scaffold (backend + frontend + CI + docker-compose Postgres), DB layer + migrations, provider abstraction + registry + `provider_fetch_log`.

### M1 — Data spine
Upstox provider + token manager (instruments, daily candles); NSE Bhavcopy (EOD spine + delivery %); corporate-action ingestion + **price adjustment** (tested).

### M2 — Analysis core
Indicator engine (DMAs, RSI, MACD, volatility, drawdown, relative strength/volume) — pure + unit-tested. Search + company-page API.

### M3 — Company page (public)
Frontend: design tokens, search, company page with **adjusted candlestick chart + split/bonus markers**, technical panel, provenance affordances.

### M4 — Fundamentals & news
Fundamental provider (best-effort, coverage-flagged) + financial panels; News provider (RSS/GDELT) + dedup + news panel.

### M5 — Opportunity & score → **Public MVP**
Opportunity screens (Layer 1) + Finder UI; Scoring engine (configurable, missing-data-graceful, peer-normalized) + breakdown UI + input snapshotting; attention ranking (Layer 2). **Deploy.**

---

## Priority tiers

### P0 — MVP (public, read-only; ~1 week target)
foundation • universe (Nifty 500) • search • company page • adjusted candlestick chart • basic financials (flagged) • basic technicals • news • opportunity finder • basic opportunity score.

### P1
authentication • portfolio • watchlist • Zerodha CSV import • AI single-company analysis (grounded + cited) • **Thesis Tracker** • provenance UI polish.

### P2
historical event/recovery engine • advanced combinable screener • full industry-specific scoring profiles • intelligent alerts (incl. thesis triggers) • natural-language research assistant • score backtesting/optimization • peer-percentile expansion • Upstox intraday/WebSocket.

## Future (beyond P2)
Expansion to US equities → mutual funds → ETFs → crypto → global assets, via new provider implementations + score profiles behind existing interfaces. Adaptive/learned scoring weights. Redis/Celery if scale demands.

## Definition of Done (MVP)
See `Build_plan.md` §W — the authoritative checklist (public company page, adjusted candlesticks with corporate-action markers, flagged fundamentals, ranked opportunities, explainable score, unattended ingestion resilient to token lapse, provenance everywhere, no secrets exposed, CI green, disclaimer present).

## Open decisions gating start
See `Build_plan.md` §V. Top three: fundamentals source for MVP • DB/host (Supabase vs Neon) • Upstox daily-token strategy.

*See also: [`../Build_plan.md`](../Build_plan.md), [`decision_log.md`](decision_log.md).*
