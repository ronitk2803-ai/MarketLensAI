import datetime as dt

import httpx
import pytest

from app.domain.models import AssetRef
from app.providers.errors import ProviderError
from app.providers.india.yfinance_fundamentals import YahooSession
from app.providers.india.yfinance_quotes import YFinanceQuoteProvider, quote_key


def _ref(symbol: str, exchange: str = "NSE") -> AssetRef:
    return AssetRef(symbol=symbol, exchange=exchange, market="IN")


def _session(handler: object, *, captured: dict | None = None) -> YahooSession:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.setdefault("urls", []).append(str(request.url))
        if "getcrumb" in str(request.url):
            return httpx.Response(200, text="test-crumb")
        if "fc.yahoo.com" in str(request.url):
            return httpx.Response(200, text="")
        return handler(request)  # type: ignore[operator]

    client = httpx.Client(transport=httpx.MockTransport(wrapped), follow_redirects=True)
    return YahooSession(client=client)


def _quote_row(symbol: str, price: float, prev: float | None = 100.0) -> dict:
    row = {
        "symbol": symbol,
        "regularMarketPrice": price,
        "regularMarketTime": 1787000000,
        "marketState": "REGULAR",
    }
    if prev is not None:
        row["regularMarketPreviousClose"] = prev
    return row


def test_parses_a_batch_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "quoteResponse": {
                    "result": [
                        _quote_row("RELIANCE.NS", 1305.0, 1316.0),
                        _quote_row("TCS.NS", 2294.8, 2302.0),
                    ]
                }
            },
        )

    provider = YFinanceQuoteProvider(session=_session(handler))
    quotes = provider.get_quote([_ref("RELIANCE"), _ref("TCS")])

    assert set(quotes) == {"NSE:RELIANCE", "NSE:TCS"}
    assert quotes["NSE:RELIANCE"].ltp == 1305.0
    assert quotes["NSE:RELIANCE"].previous_close == 1316.0
    assert quotes["NSE:RELIANCE"].market_state == "REGULAR"
    assert quotes["NSE:RELIANCE"].as_of.tzinfo is dt.UTC


def test_all_symbols_go_out_in_one_request() -> None:
    """The batch shape is the reason polling a watchlist is affordable —
    a regression to per-symbol requests would multiply upstream load by N
    without failing any other assertion."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "quoteResponse": {
                    "result": [_quote_row(f"S{i}.NS", 10.0 + i) for i in range(5)]
                }
            },
        )

    provider = YFinanceQuoteProvider(session=_session(handler, captured=captured))
    provider.get_quote([_ref(f"S{i}") for i in range(5)])

    quote_calls = [u for u in captured["urls"] if "finance/quote" in u]
    assert len(quote_calls) == 1
    assert "S0.NS" in quote_calls[0] and "S4.NS" in quote_calls[0]


def test_long_symbol_lists_are_chunked() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"quoteResponse": {"result": []}})

    provider = YFinanceQuoteProvider(session=_session(handler, captured=captured))
    provider.get_quote([_ref(f"S{i}") for i in range(120)])

    quote_calls = [u for u in captured["urls"] if "finance/quote" in u]
    assert len(quote_calls) == 3  # 120 symbols / 50 per request


def test_a_row_missing_its_price_is_skipped_not_zero_filled() -> None:
    """Substituting 0 (or a stale value) for a missing price would render as
    a real quote. Absent means the caller falls back to the stored close."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "quoteResponse": {
                    "result": [
                        {"symbol": "RELIANCE.NS", "regularMarketTime": 1787000000},
                        _quote_row("TCS.NS", 2294.8),
                    ]
                }
            },
        )

    provider = YFinanceQuoteProvider(session=_session(handler))
    quotes = provider.get_quote([_ref("RELIANCE"), _ref("TCS")])

    assert "NSE:RELIANCE" not in quotes
    assert "NSE:TCS" in quotes


def test_missing_previous_close_is_none_not_fabricated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"quoteResponse": {"result": [_quote_row("TCS.NS", 2294.8, prev=None)]}}
        )

    provider = YFinanceQuoteProvider(session=_session(handler))
    quotes = provider.get_quote([_ref("TCS")])

    assert quotes["NSE:TCS"].previous_close is None


def test_upstream_error_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    provider = YFinanceQuoteProvider(session=_session(handler))
    with pytest.raises(ProviderError):
        provider.get_quote([_ref("TCS")])


def test_empty_input_makes_no_request() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"quoteResponse": {"result": []}})

    provider = YFinanceQuoteProvider(session=_session(handler, captured=captured))
    assert provider.get_quote([]) == {}
    assert captured.get("urls") is None


def test_non_nse_exchange_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"quoteResponse": {"result": []}})

    provider = YFinanceQuoteProvider(session=_session(handler))
    with pytest.raises(ProviderError, match="unsupported exchange"):
        provider.get_quote([_ref("AAPL", exchange="NASDAQ")])


def test_quote_key_matches_the_codebase_convention() -> None:
    assert quote_key("NSE", "RELIANCE") == "NSE:RELIANCE"


def test_parses_the_forming_day_candle() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "quoteResponse": {
                    "result": [
                        {
                            **_quote_row("RELIANCE.NS", 1304.0, 1316.0),
                            "regularMarketOpen": 1316.6,
                            "regularMarketDayHigh": 1320.0,
                            "regularMarketDayLow": 1303.2,
                            "regularMarketVolume": 4834344,
                        }
                    ]
                }
            },
        )

    provider = YFinanceQuoteProvider(session=_session(handler))
    q = provider.get_quote([_ref("RELIANCE")])["NSE:RELIANCE"]

    assert (q.day_open, q.day_high, q.day_low) == (1316.6, 1320.0, 1303.2)
    assert q.day_volume == 4834344
    assert isinstance(q.day_volume, int)


def test_absent_candle_fields_are_none_not_zero() -> None:
    """A missing open rendered as 0 would draw a candle spanning the entire
    price axis; missing has to stay missing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"quoteResponse": {"result": [_quote_row("TCS.NS", 2294.8)]}}
        )

    provider = YFinanceQuoteProvider(session=_session(handler))
    q = provider.get_quote([_ref("TCS")])["NSE:TCS"]

    assert (q.day_open, q.day_high, q.day_low, q.day_volume) == (None, None, None, None)
