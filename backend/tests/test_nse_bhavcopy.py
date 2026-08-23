import datetime as dt

import httpx
import pytest

from app.domain.models import AssetRef, Bar
from app.providers.errors import ProviderError
from app.providers.india.nse_bhavcopy import (
    BhavcopyRow,
    NSEBhavcopyProvider,
    fetch_bhavcopy_raw,
    parse_bhavcopy,
)

# Real rows captured from the live sec_bhavdata_full feed on 2026-08-23, for a
# real trading day (2026-08-21) — kept verbatim so the parser is tested
# against NSE's actual header/format, including a "-" (no-delivery-data) row.
SAMPLE_CSV = (
    "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, "
    "CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
    "1018GS2026, GS, 21-Aug-2026, 104.74, 104.74, 105.00, 104.40, 105.00, 105.00, 104.75, "
    "350, 0.37, 3, 350, 100.00\n"
    "20MICRONS, EQ, 21-Aug-2026, 203.96, 208.00, 208.00, 202.73, 204.60, 204.19, 204.88, "
    "129884, 266.10, 3497, 62928, 48.45\n"
    "3IINFOLTD, BE, 21-Aug-2026, 22.25, 21.77, 23.36, 21.77, 23.36, 23.36, 23.03, "
    "233362, 53.75, 808, -, -\n"
)


def test_parse_bhavcopy_filters_to_equity_series_and_parses_fields() -> None:
    rows = parse_bhavcopy(SAMPLE_CSV)

    # GS (government security) series excluded — only EQ/BE remain.
    assert [r.symbol for r in rows] == ["20MICRONS", "3IINFOLTD"]

    micron = rows[0]
    assert micron == BhavcopyRow(
        symbol="20MICRONS",
        series="EQ",
        date=dt.date(2026, 8, 21),
        open=208.00,
        high=208.00,
        low=202.73,
        close=204.19,
        volume=129884,
        delivery_qty=62928,
        delivery_pct=48.45,
    )


def test_parse_bhavcopy_handles_missing_delivery_data() -> None:
    rows = parse_bhavcopy(SAMPLE_CSV)
    no_delivery = next(r for r in rows if r.symbol == "3IINFOLTD")
    assert no_delivery.delivery_qty is None
    assert no_delivery.delivery_pct is None


def test_fetch_bhavcopy_raw_returns_none_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_bhavcopy_raw(dt.date(2026, 8, 22), client=client) is None


def test_fetch_bhavcopy_raw_raises_on_unexpected_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        fetch_bhavcopy_raw(dt.date(2026, 8, 21), client=client)


def test_fetch_bhavcopy_raw_builds_ddmmyyyy_url() -> None:
    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text=SAMPLE_CSV)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetch_bhavcopy_raw(dt.date(2026, 8, 21), client=client)
    assert seen_urls == ["https://archives.nseindia.com/products/content/sec_bhavdata_full_21082026.csv"]


def test_get_day_bars_returns_empty_list_on_holiday() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    provider = NSEBhavcopyProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.get_day_bars(dt.date(2026, 8, 22)) == []


def test_get_day_bars_ignores_stale_data_served_for_a_no_session_date() -> None:
    """Verified live: NSE serves the last available file for a same-day/future
    request instead of 404ing — SAMPLE_CSV is dated 2026-08-21 but we ask for
    Sunday the 23rd, so the (mismatched) rows must be filtered out."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_CSV)

    provider = NSEBhavcopyProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.get_day_bars(dt.date(2026, 8, 23)) == []


def test_get_ohlcv_filters_to_one_symbol_across_date_range() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "21082026" in str(request.url):
            return httpx.Response(200, text=SAMPLE_CSV)
        return httpx.Response(404)  # 20th/22nd: no session / no match

    provider = NSEBhavcopyProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    bars = provider.get_ohlcv(
        AssetRef(symbol="20MICRONS", exchange="NSE"),
        dt.date(2026, 8, 20),
        dt.date(2026, 8, 22),
        "day",
    )

    assert bars == [
        Bar(
            date=dt.date(2026, 8, 21),
            open=208.00,
            high=208.00,
            low=202.73,
            close=204.19,
            volume=129884,
            delivery_qty=62928,
            delivery_pct=48.45,
        )
    ]


def test_get_ohlcv_rejects_non_day_interval() -> None:
    provider = NSEBhavcopyProvider()
    with pytest.raises(ProviderError):
        provider.get_ohlcv(
            AssetRef(symbol="20MICRONS", exchange="NSE"),
            dt.date(2026, 8, 21),
            dt.date(2026, 8, 21),
            "week",
        )


def test_get_universe_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        NSEBhavcopyProvider().get_universe("NIFTY_500")


def test_get_quote_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        NSEBhavcopyProvider().get_quote([AssetRef(symbol="20MICRONS", exchange="NSE")])


def test_get_corporate_actions_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        NSEBhavcopyProvider().get_corporate_actions(AssetRef(symbol="20MICRONS", exchange="NSE"))
