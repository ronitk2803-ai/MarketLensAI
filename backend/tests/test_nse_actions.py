import datetime as dt

import httpx
import pytest

from app.domain.models import AssetRef, CorporateActionEvent
from app.providers.errors import ProviderError
from app.providers.india.nse_actions import (
    NSECorporateActionsProvider,
    classify_subject,
    fetch_actions_bulk,
)

BAJFINANCE = AssetRef(symbol="BAJFINANCE", exchange="NSE")

# Real subject strings captured live 2026-08-29 against
# www.nseindia.com/api/corporates-corporateActions — this is the exact
# feed that carries the §U.11 events yfinance's chart API never did.
SAMPLE_ROWS = [
    {
        "symbol": "BAJFINANCE",
        "exDate": "16-Jun-2025",
        "subject": "Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share",
    },
    {"symbol": "BAJFINANCE", "exDate": "16-Jun-2025", "subject": "Bonus 4:1"},
    {"symbol": "BAJFINANCE", "exDate": "30-Jun-2026", "subject": "Dividend - Rs 6 Per Share"},
    {"symbol": "ABFRL", "exDate": "22-May-2025", "subject": "Demerger"},
    {"symbol": "SIEMENS", "exDate": "07-Apr-2025", "subject": "Demerger"},
    {"symbol": "360ONE", "exDate": "02-Mar-2023", "subject": "Bonus 1:1"},
    {
        "symbol": "360ONE",
        "exDate": "02-Mar-2023",
        "subject": "Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share",
    },
    # Pure calendar noise — must be dropped, not stored as "other".
    {"symbol": "VEDL", "exDate": "03-Aug-2022", "subject": "Annual General Meeting"},
    {"symbol": "VEDL", "exDate": "09-Mar-2022", "subject": "Interim Dividend"},
    # Unparseable ex_date — dropped rather than fabricating a date.
    {"symbol": "TESTCO", "exDate": "-", "subject": "Bonus 1:1"},
]


# --- classify_subject -------------------------------------------------


def test_classify_bonus_ratio_from_n_to_m() -> None:
    assert classify_subject("Bonus 4:1") == ("bonus", 5.0, None)
    assert classify_subject("Bonus 1:1") == ("bonus", 2.0, None)


def test_classify_face_value_split_ratio_is_exact_not_guessed() -> None:
    assert classify_subject(
        "Face Value Split (Sub-Division) - From Rs 5/- Per Share To Re 1/- Per Share"
    ) == ("split", 5.0, None)
    assert classify_subject(
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"
    ) == ("split", 5.0, None)


def test_classify_split_like_text_without_parseable_ratio_is_other_not_split() -> None:
    """Never type it "split" without a real ratio — that would make the
    frontend's EXPLAINED_ACTION_TYPES call it handled when it wasn't."""
    result = classify_subject("Stock Split approved by the board")
    assert result is not None
    assert result[0] == "other"
    assert result[1] is None


def test_classify_demerger_and_related_schemes() -> None:
    for subject in (
        "Demerger",
        "Scheme of Arrangement",
        "Amalgamation",
        "Reduction of Capital",
    ):
        action_type, ratio, amount = classify_subject(subject)
        assert action_type == "demerger"
        assert ratio is None
        assert amount is None


def test_classify_rights_issue() -> None:
    assert classify_subject("Rights Issue") == ("rights", None, None)


def test_classify_dividend_extracts_amount() -> None:
    assert classify_subject("Dividend - Rs 44 Per Share") == ("dividend", None, 44.0)
    assert classify_subject("Interim Dividend - Rs 8.50 Per Share") == ("dividend", None, 8.5)


def test_classify_dividend_without_parseable_amount_keeps_type() -> None:
    action_type, ratio, amount = classify_subject("Interim Dividend")
    assert action_type == "dividend"
    assert ratio is None
    assert amount is None


def test_classify_calendar_noise_returns_none() -> None:
    assert classify_subject("Annual General Meeting") is None
    assert classify_subject("Board Meeting") is None
    assert classify_subject("Interest Payment") is None
    assert classify_subject("") is None


def test_classify_zero_denominator_bonus_does_not_divide_by_zero() -> None:
    # "Bonus 1:0" isn't real-world data, but classify_subject must never
    # raise on adversarial/malformed input from an external feed.
    assert classify_subject("Bonus 1:0") == ("other", None, None)


# --- fetch_actions_bulk -------------------------------------------------


def test_fetch_actions_bulk_groups_by_symbol_and_matches_known_gaps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_ROWS)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    by_symbol = fetch_actions_bulk(dt.date(2020, 1, 1), dt.date(2026, 12, 31), client=client)

    assert by_symbol["BAJFINANCE"] == [
        CorporateActionEvent(type="split", ex_date=dt.date(2025, 6, 16), ratio=2.0),
        CorporateActionEvent(type="bonus", ex_date=dt.date(2025, 6, 16), ratio=5.0),
        CorporateActionEvent(type="dividend", ex_date=dt.date(2026, 6, 30), amount=6.0),
    ]
    assert by_symbol["ABFRL"] == [
        CorporateActionEvent(type="demerger", ex_date=dt.date(2025, 5, 22))
    ]
    assert by_symbol["SIEMENS"] == [
        CorporateActionEvent(type="demerger", ex_date=dt.date(2025, 4, 7))
    ]
    assert by_symbol["360ONE"] == [
        CorporateActionEvent(type="bonus", ex_date=dt.date(2023, 3, 2), ratio=2.0),
        CorporateActionEvent(type="split", ex_date=dt.date(2023, 3, 2), ratio=2.0),
    ]
    # AGM dropped; the real Interim Dividend (no parseable amount) kept.
    assert by_symbol["VEDL"] == [
        CorporateActionEvent(type="dividend", ex_date=dt.date(2022, 3, 9))
    ]
    # Unparseable ex_date row dropped entirely.
    assert "TESTCO" not in by_symbol


def test_fetch_actions_bulk_sends_the_full_date_range() -> None:
    seen_params = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetch_actions_bulk(dt.date(2021, 8, 25), dt.date(2026, 8, 29), client=client)

    assert seen_params[0]["from_date"] == "25-08-2021"
    assert seen_params[0]["to_date"] == "29-08-2026"
    assert seen_params[0]["index"] == "equities"
    assert "symbol" not in seen_params[0]


def test_fetch_actions_bulk_raises_on_non_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        fetch_actions_bulk(dt.date(2020, 1, 1), dt.date(2020, 12, 31), client=client)


def test_fetch_actions_bulk_raises_on_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated block")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        fetch_actions_bulk(dt.date(2020, 1, 1), dt.date(2020, 12, 31), client=client)


# --- NSECorporateActionsProvider -----------------------------------------


def test_provider_scopes_the_query_to_one_symbol() -> None:
    seen_params = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.append(dict(request.url.params))
        return httpx.Response(
            200,
            json=[r for r in SAMPLE_ROWS if r["symbol"] == "BAJFINANCE"],
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = NSECorporateActionsProvider(client=client)
    events = provider.get_corporate_actions(BAJFINANCE)

    assert seen_params[0]["symbol"] == "BAJFINANCE"
    assert len(events) == 3
    assert events == sorted(events, key=lambda e: e.ex_date)


def test_provider_rejects_non_nse_exchange() -> None:
    provider = NSECorporateActionsProvider()
    with pytest.raises(ProviderError):
        provider.get_corporate_actions(AssetRef(symbol="AAPL", exchange="NASDAQ"))
