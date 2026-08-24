import datetime as dt
import gzip
import json

import httpx
import pytest

from app.domain.models import AssetRef, Bar
from app.providers.auth.upstox_token_manager import IST, UpstoxTokenManager
from app.providers.errors import ProviderError
from app.providers.india.upstox import (
    UpstoxInstrument,
    UpstoxMarketDataProvider,
    fetch_instruments_raw,
    parse_equity_instruments,
)

SAMPLE_INSTRUMENTS = [
    {
        "segment": "NSE_EQ",
        "name": "RELIANCE INDUSTRIES LTD",
        "exchange": "NSE",
        "isin": "INE002A01018",
        "instrument_type": "EQ",
        "instrument_key": "NSE_EQ|INE002A01018",
        "trading_symbol": "RELIANCE",
    },
    {
        # Derivative on the same underlying — must be filtered out.
        "segment": "NSE_FO",
        "name": "RELIANCE FUT",
        "exchange": "NSE",
        "isin": "INE002A01018",
        "instrument_type": "FUT",
        "instrument_key": "NSE_FO|12345",
        "trading_symbol": "RELIANCE26AUGFUT",
    },
    {
        "segment": "NSE_INDEX",
        "name": "NIFTY 50",
        "exchange": "NSE",
        "isin": None,
        "instrument_type": "INDEX",
        "instrument_key": "NSE_INDEX|Nifty 50",
        "trading_symbol": "NIFTY 50",
    },
]


def test_parse_equity_instruments_includes_be_series() -> None:
    """Regression test: E2E Networks (trading_symbol "E2E") trades in NSE's
    BE series, and the original filter accepted only instrument_type "EQ",
    silently dropping it (and any other BE-series stock) before it ever
    became an Asset row. nse_bhavcopy.EQUITY_SERIES already treats BE as
    ordinary equity — this filter has to agree with that, not just EQ."""
    be_stock = {
        "segment": "NSE_EQ",
        "name": "E2E NETWORKS LIMITED",
        "exchange": "NSE",
        "isin": "INE255Z01027",
        "instrument_type": "BE",
        "instrument_key": "NSE_EQ|INE255Z01027",
        "trading_symbol": "E2E",
    }

    instruments = parse_equity_instruments(json.dumps([*SAMPLE_INSTRUMENTS, be_stock]))

    assert any(i.trading_symbol == "E2E" for i in instruments)


def test_parse_equity_instruments_filters_to_nse_eq_only() -> None:
    instruments = parse_equity_instruments(json.dumps(SAMPLE_INSTRUMENTS))
    assert instruments == [
        UpstoxInstrument(
            instrument_key="NSE_EQ|INE002A01018",
            trading_symbol="RELIANCE",
            name="RELIANCE INDUSTRIES LTD",
            isin="INE002A01018",
            exchange="NSE",
        )
    ]


def test_fetch_instruments_raw_gunzips_response() -> None:
    payload = gzip.compress(json.dumps(SAMPLE_INSTRUMENTS).encode())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    raw = fetch_instruments_raw("NSE", client=client)
    assert json.loads(raw) == SAMPLE_INSTRUMENTS


def test_fetch_instruments_raw_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        fetch_instruments_raw("NSE", client=client)


RELIANCE = AssetRef(symbol="RELIANCE", exchange="NSE")


def _token_manager_with_token() -> UpstoxTokenManager:
    # Deliberately no obtained_at — these tests need a token that is live
    # whenever the suite runs. Pinning a date made them expire at 03:30 IST
    # the morning after they were written.
    manager = UpstoxTokenManager()
    manager.set_token("tok_live")
    return manager


def test_get_ohlcv_parses_candles_and_uses_bearer_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok_live"
        url = str(request.url)
        assert "NSE_EQ%7CINE002A01018" in url or "NSE_EQ|INE002A01018" in url
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "candles": [
                        ["2026-08-21T00:00:00+05:30", 1400.0, 1420.5, 1395.0, 1410.25, 1_000_000, 0]
                    ]
                },
            },
        )

    provider = UpstoxMarketDataProvider(
        _token_manager_with_token(),
        resolve_instrument_key=lambda asset: "NSE_EQ|INE002A01018",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    bars = provider.get_ohlcv(RELIANCE, dt.date(2026, 8, 1), dt.date(2026, 8, 21), "day")

    assert bars == [
        Bar(
            date=dt.date(2026, 8, 21),
            open=1400.0,
            high=1420.5,
            low=1395.0,
            close=1410.25,
            volume=1_000_000,
            oi=None,
        )
    ]


def test_get_ohlcv_rejects_unsupported_interval() -> None:
    provider = UpstoxMarketDataProvider(
        _token_manager_with_token(), resolve_instrument_key=lambda asset: "NSE_EQ|X"
    )
    with pytest.raises(ProviderError):
        provider.get_ohlcv(RELIANCE, dt.date(2026, 8, 1), dt.date(2026, 8, 21), "1minute")


def test_get_ohlcv_propagates_expired_token() -> None:
    expired = UpstoxTokenManager()
    expired.set_token("tok", obtained_at=dt.datetime(2020, 1, 1, 9, 0, tzinfo=IST))
    provider = UpstoxMarketDataProvider(expired, resolve_instrument_key=lambda asset: "NSE_EQ|X")
    with pytest.raises(ProviderError):
        provider.get_ohlcv(RELIANCE, dt.date(2026, 8, 1), dt.date(2026, 8, 21), "day")


def test_get_ohlcv_upstream_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream down")

    provider = UpstoxMarketDataProvider(
        _token_manager_with_token(),
        resolve_instrument_key=lambda asset: "NSE_EQ|X",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ProviderError):
        provider.get_ohlcv(RELIANCE, dt.date(2026, 8, 1), dt.date(2026, 8, 21), "day")


def test_get_universe_returns_nse_equities_only() -> None:
    payload = gzip.compress(json.dumps(SAMPLE_INSTRUMENTS).encode())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    provider = UpstoxMarketDataProvider(
        _token_manager_with_token(),
        resolve_instrument_key=lambda asset: "NSE_EQ|X",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    universe = provider.get_universe("NIFTY_500")

    assert universe == [
        AssetRef(
            symbol="RELIANCE", exchange="NSE", market="IN", name="RELIANCE INDUSTRIES LTD",
            isin="INE002A01018",
        )
    ]


def test_get_quote_not_implemented() -> None:
    provider = UpstoxMarketDataProvider(
        _token_manager_with_token(), resolve_instrument_key=lambda asset: "NSE_EQ|X"
    )
    with pytest.raises(NotImplementedError):
        provider.get_quote([RELIANCE])


def test_get_corporate_actions_not_implemented() -> None:
    provider = UpstoxMarketDataProvider(
        _token_manager_with_token(), resolve_instrument_key=lambda asset: "NSE_EQ|X"
    )
    with pytest.raises(NotImplementedError):
        provider.get_corporate_actions(RELIANCE)
