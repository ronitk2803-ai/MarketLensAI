import datetime as dt

import httpx
import pytest

from app.domain.models import AssetRef, CorporateActionEvent
from app.providers.errors import ProviderError
from app.providers.india.yfinance_actions import (
    YFinanceCorporateActionsProvider,
    fetch_actions_raw,
    parse_actions,
)

RELIANCE = AssetRef(symbol="RELIANCE", exchange="NSE")

# Trimmed real response shape from Yahoo's chart API for RELIANCE.NS,
# captured live 2026-08-23 (full history has many more dividends).
SAMPLE_BODY = {
    "chart": {
        "result": [
            {
                "meta": {"symbol": "RELIANCE.NS"},
                "events": {
                    "splits": {
                        "1504755900": {
                            "date": 1504755900,
                            "numerator": 2.0,
                            "denominator": 1.0,
                            "splitRatio": "2:1",
                        },
                        "1730087100": {
                            "date": 1730087100,
                            "numerator": 2.0,
                            "denominator": 1.0,
                            "splitRatio": "2:1",
                        },
                    },
                    "dividends": {
                        "1623383100": {"amount": 3.5, "date": 1623383100},
                    },
                },
            }
        ],
        "error": None,
    }
}


def test_parse_actions_maps_splits_and_dividends_sorted_by_date() -> None:
    actions = parse_actions(SAMPLE_BODY)

    assert actions == [
        CorporateActionEvent(type="split", ex_date=dt.date(2017, 9, 7), ratio=2.0),
        CorporateActionEvent(type="dividend", ex_date=dt.date(2021, 6, 11), amount=3.5),
        CorporateActionEvent(type="split", ex_date=dt.date(2024, 10, 28), ratio=2.0),
    ]


def test_parse_actions_handles_no_events() -> None:
    body = {"chart": {"result": [{"meta": {}, "events": {}}]}}
    assert parse_actions(body) == []


def test_fetch_actions_raw_rejects_non_nse_exchange() -> None:
    with pytest.raises(ProviderError):
        fetch_actions_raw(AssetRef(symbol="AAPL", exchange="NASDAQ"))


def test_fetch_actions_raw_appends_ns_suffix() -> None:
    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, json=SAMPLE_BODY)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetch_actions_raw(RELIANCE, client=client)
    assert "RELIANCE.NS" in seen_urls[0]


def test_fetch_actions_raw_surfaces_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"chart": {"result": None, "error": {"description": "Not Found"}}}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        fetch_actions_raw(RELIANCE, client=client)


def test_fetch_actions_raw_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        fetch_actions_raw(RELIANCE, client=client)


def test_provider_get_corporate_actions_end_to_end() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_BODY)

    provider = YFinanceCorporateActionsProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    actions = provider.get_corporate_actions(RELIANCE)
    assert len(actions) == 3
