"""NSE's own daily "all indices" close file — carries P/E, P/B, and
dividend yield per index, including the Nifty sectoral indices (Nifty
Auto, Nifty IT, Nifty Financial Services, ...). This is the real answer
to "what's this sector's P/E" — computed by NSE itself across an index's
full constituent set, not derived from whichever handful of companies
this app happens to have fundamentals cached for (see
app/services/fundamentals.py's get_sector_ratio_stats, which now only
serves as a fallback for the couple of industries with no matching
sectoral index).

Reachable because it lives on the same auth-free archives.nseindia.com
host as Bhavcopy (nse_bhavcopy.py) and the index constituent lists
(nse_indices.py) — unlike www.nseindia.com's live JSON APIs, which are
blocked by Akamai bot protection at the connection level from this
environment (see yfinance_actions.py's docstring). Verified live
2026-08-25: `ind_close_all_{DDMMYYYY}.csv` returns real data with the same
plain-httpx-client, no-cookie-bootstrap shape as the other archives files.
"""

import csv
import datetime as dt
import io
from dataclasses import dataclass

import httpx

from app.providers.errors import ProviderError

INDEX_PE_URL = "https://archives.nseindia.com/content/indices/ind_close_all_{date}.csv"

# How many calendar days to walk back looking for the most recent
# published file — NSE doesn't publish on weekends/holidays, and "give me
# today's" has to degrade to "give me the last trading day's" the same way
# a human checking the site would.
MAX_LOOKBACK_DAYS = 7


@dataclass(frozen=True, slots=True)
class IndexPeRow:
    index_name: str
    pe: float | None
    pb: float | None
    div_yield: float | None
    index_date: dt.date


def _parse_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or raw == "-":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def fetch_index_pe_raw(date: dt.date, *, client: httpx.Client | None = None) -> str | None:
    """Raw CSV text for `date`, or None if NSE has nothing published for it
    (weekend/holiday) — same 404-means-no-session convention as Bhavcopy."""
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        response = client.get(
            INDEX_PE_URL.format(date=date.strftime("%d%m%Y")),
            # Same UA workaround as nse_indices.py — the archives host
            # occasionally trips on a default httpx UA.
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        )
    finally:
        if owns_client:
            client.close()

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ProviderError("nse_sector_pe", f"index PE fetch failed: {response.status_code}")
    return response.text


def parse_index_pe(raw_csv: str, index_date: dt.date) -> list[IndexPeRow]:
    """Columns: Index Name, Index Date, Open/High/Low/Closing Index Value,
    Points Change, Change(%), Volume, Turnover (Rs. Cr.), P/E, P/B, Div
    Yield. Missing figures (a strategy index with no meaningful P/E, e.g.
    "India VIX") are the literal string "-", not absent — that's what
    `_parse_float` treats as None rather than a parse error."""
    reader = csv.DictReader(io.StringIO(raw_csv))
    rows = []
    for row in reader:
        name = (row.get("Index Name") or "").strip()
        if not name:
            continue
        rows.append(
            IndexPeRow(
                index_name=name,
                pe=_parse_float(row.get("P/E")),
                pb=_parse_float(row.get("P/B")),
                div_yield=_parse_float(row.get("Div Yield")),
                index_date=index_date,
            )
        )
    return rows


def fetch_latest_index_pe(*, client: httpx.Client | None = None) -> list[IndexPeRow]:
    """Walks back from today to find the most recently published file —
    the shape callers actually want ("today's sector P/E," which on a
    weekend/holiday means the last trading day's)."""
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        date = dt.date.today()
        for _ in range(MAX_LOOKBACK_DAYS):
            raw = fetch_index_pe_raw(date, client=client)
            if raw is not None:
                return parse_index_pe(raw, date)
            date -= dt.timedelta(days=1)
        raise ProviderError(
            "nse_sector_pe", f"no index PE file found in the last {MAX_LOOKBACK_DAYS} days"
        )
    finally:
        if owns_client:
            client.close()
