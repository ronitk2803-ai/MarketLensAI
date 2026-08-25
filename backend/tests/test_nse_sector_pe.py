import datetime as dt

import httpx
import pytest

from app.providers.errors import ProviderError
from app.providers.india.nse_sector_pe import (
    IndexPeRow,
    fetch_index_pe_raw,
    fetch_latest_index_pe,
    parse_index_pe,
)

# Header and a real subset of rows, copied verbatim from the live
# ind_close_all CSV (fetched 2026-08-25) so the parser is pinned against
# the actual format — including the "-" sentinel NSE uses for indices with
# no meaningful P/E (India VIX) rather than omitting the field.
REAL_CSV = """Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield
Nifty 50,24-08-2026,24285.05,24313,24144.3,24219.05,-32.95,-.14,236285363,17854.63,20.47,2.94,1.16
Nifty Financial Services,24-08-2026,26272.3,26361.65,26088.9,26158.5,-102.5,-.39,90319568,8440.44,16.04,2.43,.94
India VIX,24-08-2026,11.195,11.76,10.3225,11.53,0.33,2.95,-,-,-,-,-
"""


def test_parse_index_pe_reads_the_live_format() -> None:
    rows = parse_index_pe(REAL_CSV, dt.date(2026, 8, 24))

    assert rows[0] == IndexPeRow(
        index_name="Nifty 50", pe=20.47, pb=2.94, div_yield=1.16, index_date=dt.date(2026, 8, 24)
    )
    assert rows[1].index_name == "Nifty Financial Services"
    assert rows[1].pe == 16.04


def test_parse_index_pe_treats_dash_as_missing_not_zero() -> None:
    """India VIX has no P/E — NSE marks that "-", not 0. Reading it as a
    real zero would fabricate a number that was never there."""
    rows = parse_index_pe(REAL_CSV, dt.date(2026, 8, 24))

    vix = next(r for r in rows if r.index_name == "India VIX")
    assert vix.pe is None
    assert vix.pb is None
    assert vix.div_yield is None


def test_fetch_index_pe_raw_returns_none_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_index_pe_raw(dt.date(2026, 8, 24), client=client) is None


def test_fetch_index_pe_raw_raises_on_unexpected_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        fetch_index_pe_raw(dt.date(2026, 8, 24), client=client)


def test_fetch_latest_index_pe_walks_back_until_a_day_resolves() -> None:
    """A weekend/holiday 404s (no session that day); the walk-back has to
    keep trying earlier dates rather than giving up on the first miss —
    same "no session that day" shape as Bhavcopy."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:  # first two attempts: no session that day
            return httpx.Response(404)
        return httpx.Response(200, text=REAL_CSV)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = fetch_latest_index_pe(client=client)

    assert calls["n"] == 3
    assert rows[0].index_name == "Nifty 50"


def test_fetch_latest_index_pe_raises_after_exhausting_lookback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="no index PE file found"):
        fetch_latest_index_pe(client=client)
