# Decision Log — `mlai`

> Append-only record of decisions that are expensive to reverse, with the reason. Newest at top.
> Codename `mlai` used everywhere; final brand decided later.

---

## 2026-08-11

### D-007 — Corporate actions: chart is auto-adjusted AND annotated
- **Decision:** The price chart displays **corporate-action-adjusted** prices by default, AND places a **visible marker on the ex-date** (e.g. "1:2 split", "1:1 bonus", dividend) so users see *why* the series steps. Optionally a raw/adjusted toggle later.
- **Why:** Adjustment prevents a split from looking like a crash; the marker preserves transparency (facts over hidden manipulation) — consistent with the evidence/provenance principle.
- **Impact:** `corporate_action` drives an adjustment step in ingestion; frontend renders markers from the same table.

### D-006 — Store full daily bars for ALL available history
- **Decision:** Persist complete daily bars — **Open, High, Low, Close, Volume, Open Interest, delivery qty & %** — for the full available history in our own Postgres, not a reduced OHLC-only set.
- **Why:** Past comparison ("has this happened before?"), the Volume Philosophy (§9), unusual-volume/participation screens, and candlestick charts all require the full bar. Storage cost is negligible (~500 stocks × daily × a few numbers).
- **Supersedes:** earlier idea of storing only O/H/L/C without volume, and showing only open/close on historical charts. **Full candlesticks are now the default.**

### D-005 — Charts render candlesticks from stored OHLC
- **Decision:** Historical price chart = candlesticks (O/H/L/C) from our DB; a close-only line view may be offered for long-range zoom.
- **Why:** We store all four values anyway, so candles are "free" and more informative; line view kept for clean long-term readability.

### D-004 — Current-day live data from Upstox (free broker API)
- **Decision:** Today's LTP / quote / intraday / streaming comes live from Upstox; the EOD job writes the final daily bar into the DB. Live only for the current day; past days served from DB.
- **Why:** EOD-first keeps cost/complexity low; live only where it matters (today).
- **Caveat:** Upstox token expires daily → NSE Bhavcopy remains the auth-free EOD spine so history never depends on a live token.

### D-003 — Free-first data strategy; paid feeds later behind the provider interface
- **Decision:** Build entirely on free sources first (see `API_Sources.md`). Paid feeds (e.g. EODHD for fundamentals) added later only when a specific gap justifies it, dropped in behind `MarketDataProvider` / `FundamentalDataProvider` with zero rewrite.
- **Why:** Budget ~₹0; ₹500/mo does not buy quality Indian fundamentals anyway (real fix is ~₹1,700–5,000/mo).

### D-002 — Fundamentals: partial + flagged, never fabricated
- **Decision:** Ship best-effort fundamentals with explicit `source + as_of + confidence`; missing data shown as "unavailable," never guessed. Curated Nifty 500 seed for MVP reliability; XBRL parser is P2.
- **Why:** No free source gives correct+complete Indian fundamentals; correctness > completeness.

### D-001 — Upstox is the preferred market-data provider; Bhavcopy is the unattended spine
- **Decision:** Upstox primary for prices/quotes; NSE Bhavcopy (auth-free) as the guaranteed EOD spine + delivery %; Angel/Fyers/Dhan as broker fallbacks; yfinance for backfill/cross-check.
- **Why:** Redundancy + correctness (two-source reconciliation) with no single point of failure.

---
*Template: `### D-XXX — <title>` / **Decision** / **Why** / **Impact or Caveat**.*
