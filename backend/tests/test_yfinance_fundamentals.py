import datetime as dt

import httpx
import pytest

from app.domain.models import AssetRef
from app.providers.errors import ProviderError
from app.providers.india.yfinance_fundamentals import (
    YahooSession,
    YFinanceFundamentalDataProvider,
    _extract,
    fetch_quote_summary,
    parse_ratios,
    parse_statements,
)

RELIANCE = AssetRef(symbol="RELIANCE", exchange="NSE")

# Real response shapes captured live 2026-08-23 (trimmed). Yahoo's "no data"
# sentinel is raw=0/fmt=null, distinct from a real zero.
RATIOS_BODY = {
    "financialData": {
        "debtToEquity": {"raw": 36.653, "fmt": "36.65%"},
        "grossMargins": {"raw": 0.33837003, "fmt": "33.84%"},
        "returnOnEquity": {},
        "freeCashflow": {"raw": 0, "fmt": None, "longFmt": "0"},
    },
    "defaultKeyStatistics": {
        "priceToBook": {"raw": 1.9699272, "fmt": "1.97"},
        "beta": {"raw": 0.157, "fmt": "0.16"},
    },
}

INCOME_STATEMENT_BODY = {
    "incomeStatementHistory": {
        "incomeStatementHistory": [
            {
                "endDate": {"raw": 1774915200, "fmt": "2026-03-31"},
                "totalRevenue": {"raw": 10572190000000, "fmt": "10.57T"},
                "costOfRevenue": {"raw": 0, "fmt": None, "longFmt": "0"},
                "grossProfit": {"raw": 0, "fmt": None, "longFmt": "0"},
                "ebit": {"raw": 0, "fmt": None, "longFmt": "0"},
                "netIncome": {"raw": 438510000000, "fmt": "438.51B"},
            },
            {
                "endDate": {"raw": 1743379200, "fmt": "2025-03-31"},
                "totalRevenue": {"raw": 5173490000000, "fmt": "5.17T"},
                "netIncome": {"raw": 352620000000, "fmt": "352.62B"},
            },
        ]
    }
}

EMPTY_BALANCE_SHEET_BODY = {
    "balanceSheetHistory": {
        "balanceSheetStatements": [
            {"endDate": {"raw": 1774915200, "fmt": "2026-03-31"}},
        ]
    }
}


def test_extract_rejects_the_no_data_sentinel() -> None:
    # raw=0 with fmt=None is Yahoo's "no data" marker, not a real zero.
    assert _extract({"raw": 0, "fmt": None, "longFmt": "0"}) is None
    assert _extract({}) is None
    assert _extract(None) is None


def test_extract_accepts_a_genuine_zero() -> None:
    # A real reported zero has a non-null fmt.
    assert _extract({"raw": 0, "fmt": "0.00"}) == 0.0


def test_extract_returns_real_value() -> None:
    assert _extract({"raw": 36.653, "fmt": "36.65%"}) == 36.653


def test_parse_ratios_includes_only_present_fields() -> None:
    ratios = parse_ratios(RELIANCE, RATIOS_BODY)
    assert ratios.values == {
        "debtToEquity": 36.653,
        "grossMargins": 0.33837003,
        "priceToBook": 1.9699272,
        "beta": 0.157,
    }
    assert "returnOnEquity" not in ratios.values
    assert "freeCashflow" not in ratios.values


def test_parse_ratios_falls_back_to_summary_detail_for_trailing_pe() -> None:
    """Regression test: trailingPE — the number people actually mean by
    "P/E ratio" (forwardPE is a different, forward-looking figure) — was
    missing from every company's fundamentals panel. Verified live across
    RELIANCE/TCS/INFY: Yahoo only ever puts it in summaryDetail, never in
    financialData or defaultKeyStatistics, which is all get_ratios used to
    request."""
    body = {
        "financialData": {"debtToEquity": {"raw": 36.653, "fmt": "36.65%"}},
        "defaultKeyStatistics": {"priceToBook": {"raw": 1.97, "fmt": "1.97"}},
        "summaryDetail": {"trailingPE": {"raw": 23.69821, "fmt": "23.70"}},
    }

    ratios = parse_ratios(RELIANCE, body)

    assert ratios.values["trailingPE"] == 23.69821


def test_parse_ratios_prefers_earlier_modules_when_a_field_is_in_several() -> None:
    body = {
        "financialData": {"beta": {"raw": 0.5, "fmt": "0.50"}},
        "defaultKeyStatistics": {},
        "summaryDetail": {"beta": {"raw": 0.99, "fmt": "0.99"}},
    }

    ratios = parse_ratios(RELIANCE, body)

    assert ratios.values["beta"] == 0.5  # financialData wins, not summaryDetail


def test_parse_ratios_does_not_drop_a_genuine_zero_to_a_later_module() -> None:
    """`or`-chaining the three module lookups would treat a real 0.0 as
    falsy and silently pull a *different* module's value for the same
    field instead — this pins that beta=0.0 from financialData is kept,
    not overridden by summaryDetail's non-zero beta."""
    body = {
        "financialData": {"beta": {"raw": 0.0, "fmt": "0.00"}},
        "defaultKeyStatistics": {},
        "summaryDetail": {"beta": {"raw": 1.2, "fmt": "1.20"}},
    }

    ratios = parse_ratios(RELIANCE, body)

    assert ratios.values["beta"] == 0.0


def test_parse_statements_extracts_only_populated_line_items() -> None:
    statements = parse_statements(RELIANCE, INCOME_STATEMENT_BODY, "income", "FY")

    assert len(statements) == 2
    latest = statements[0]
    assert latest.period_end == dt.date(2026, 3, 31)
    assert latest.period_type == "FY"
    assert latest.line_items == {"totalRevenue": 10572190000000.0, "netIncome": 438510000000.0}
    # costOfRevenue/grossProfit/ebit were all the no-data sentinel -> absent, not zero.
    assert "costOfRevenue" not in latest.line_items
    assert "grossProfit" not in latest.line_items


def test_parse_statements_skips_periods_with_no_real_data() -> None:
    statements = parse_statements(RELIANCE, EMPTY_BALANCE_SHEET_BODY, "balance_sheet", "FY")
    assert statements == []


def _mock_session(handler: httpx.MockTransport) -> YahooSession:
    return YahooSession(client=httpx.Client(transport=handler))


def test_yahoo_session_bootstraps_crumb_then_calls_endpoint() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "getcrumb" in str(request.url):
            return httpx.Response(200, text="abc123")
        if "fc.yahoo.com" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, json={"ok": True})

    session = _mock_session(httpx.MockTransport(handler))
    response = session.get("https://query1.finance.yahoo.com/v10/finance/quoteSummary/X", params={})

    assert response.status_code == 200
    assert any("getcrumb" in c for c in calls)
    assert any("crumb=abc123" in c for c in calls)


def test_yahoo_session_rebootstraps_once_on_401() -> None:
    crumb_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal crumb_calls
        url = str(request.url)
        if "getcrumb" in url:
            crumb_calls += 1
            return httpx.Response(200, text=f"crumb{crumb_calls}")
        if "fc.yahoo.com" in url:
            return httpx.Response(404)
        if "crumb=crumb1" in url:
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True})

    session = _mock_session(httpx.MockTransport(handler))
    response = session.get("https://query1.finance.yahoo.com/v10/finance/quoteSummary/X", params={})

    assert response.status_code == 200
    assert crumb_calls == 2


def test_fetch_quote_summary_raises_on_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "getcrumb" in str(request.url):
            return httpx.Response(200, text="crumb")
        if "fc.yahoo.com" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(
            200, json={"quoteSummary": {"result": None, "error": {"description": "Not Found"}}}
        )

    session = _mock_session(httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        fetch_quote_summary(RELIANCE, ["financialData"], session=session)


def test_fetch_quote_summary_rejects_non_nse() -> None:
    session = _mock_session(httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ProviderError):
        fetch_quote_summary(
            AssetRef(symbol="AAPL", exchange="NASDAQ"), ["financialData"], session=session
        )


def test_provider_get_ratios_end_to_end() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "getcrumb" in str(request.url):
            return httpx.Response(200, text="crumb")
        if "fc.yahoo.com" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, json={"quoteSummary": {"result": [RATIOS_BODY]}})

    provider = YFinanceFundamentalDataProvider(session=_mock_session(httpx.MockTransport(handler)))
    ratios = provider.get_ratios(RELIANCE)
    assert ratios.values["debtToEquity"] == 36.653


def test_provider_get_statements_returns_most_recent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "getcrumb" in str(request.url):
            return httpx.Response(200, text="crumb")
        if "fc.yahoo.com" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, json={"quoteSummary": {"result": [INCOME_STATEMENT_BODY]}})

    provider = YFinanceFundamentalDataProvider(session=_mock_session(httpx.MockTransport(handler)))
    statement = provider.get_statements(RELIANCE, "FY")
    assert statement.period_end == dt.date(2026, 3, 31)


def test_provider_get_all_statements_rejects_unsupported_combo() -> None:
    session = _mock_session(httpx.MockTransport(lambda r: httpx.Response(200)))
    provider = YFinanceFundamentalDataProvider(session=session)
    with pytest.raises(ProviderError):
        provider.get_all_statements(RELIANCE, "income", "10Y")
