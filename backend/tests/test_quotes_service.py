import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset
from app.domain.models import AssetRef, Quote
from app.providers.errors import ProviderError
from app.services import quotes as quotes_service


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    quotes_service.clear_cache()
    yield
    quotes_service.clear_cache()


def _asset(db: Session, symbol: str) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    return asset


def _quote(symbol: str, ltp: float) -> Quote:
    return Quote(
        asset=AssetRef(symbol=symbol, exchange="NSE", market="IN"),
        ltp=ltp,
        as_of=dt.datetime.now(dt.UTC),
        previous_close=100.0,
        market_state="REGULAR",
    )


class _SpyProvider:
    def __init__(self, quotes: dict[str, Quote] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._quotes = quotes or {}

    def get_quote(self, assets: list[AssetRef]) -> dict[str, Quote]:
        self.calls.append([a.symbol for a in assets])
        return {k: v for k, v in self._quotes.items() if any(a.symbol in k for a in assets)}


def test_returns_quotes_keyed_by_exchange_and_symbol(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _asset(db, "ZZQ1")
    spy = _SpyProvider({"NSE:ZZQ1": _quote("ZZQ1", 123.4)})
    monkeypatch.setattr(quotes_service, "_provider", spy)

    result = quotes_service.get_live_quotes(db, ["ZZQ1"])

    assert result["NSE:ZZQ1"].ltp == 123.4


def test_a_second_call_within_the_ttl_does_not_hit_the_provider(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache is what stops upstream load scaling with viewers rather
    than symbols — every open tab polls this endpoint."""
    _asset(db, "ZZQ2")
    spy = _SpyProvider({"NSE:ZZQ2": _quote("ZZQ2", 50.0)})
    monkeypatch.setattr(quotes_service, "_provider", spy)

    quotes_service.get_live_quotes(db, ["ZZQ2"])
    quotes_service.get_live_quotes(db, ["ZZQ2"])
    quotes_service.get_live_quotes(db, ["ZZQ2"])

    assert len(spy.calls) == 1


def test_an_expired_entry_is_refetched(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _asset(db, "ZZQ3")
    spy = _SpyProvider({"NSE:ZZQ3": _quote("ZZQ3", 50.0)})
    monkeypatch.setattr(quotes_service, "_provider", spy)
    monkeypatch.setattr(quotes_service, "CACHE_TTL", dt.timedelta(seconds=-1))

    quotes_service.get_live_quotes(db, ["ZZQ3"])
    quotes_service.get_live_quotes(db, ["ZZQ3"])

    assert len(spy.calls) == 2


def test_only_uncached_symbols_are_fetched(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _asset(db, "ZZQ4")
    _asset(db, "ZZQ5")
    spy = _SpyProvider(
        {"NSE:ZZQ4": _quote("ZZQ4", 10.0), "NSE:ZZQ5": _quote("ZZQ5", 20.0)}
    )
    monkeypatch.setattr(quotes_service, "_provider", spy)

    quotes_service.get_live_quotes(db, ["ZZQ4"])
    result = quotes_service.get_live_quotes(db, ["ZZQ4", "ZZQ5"])

    assert spy.calls == [["ZZQ4"], ["ZZQ5"]]  # second call fetched only the miss
    assert set(result) == {"NSE:ZZQ4", "NSE:ZZQ5"}


def test_provider_failure_degrades_to_empty_rather_than_raising(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live quotes are an enhancement over stored closes, never a
    dependency — a Yahoo outage must not take out the page."""
    _asset(db, "ZZQ6")

    class _Boom:
        def get_quote(self, assets: list[AssetRef]) -> dict[str, Quote]:
            raise ProviderError("yfinance_quotes", "simulated outage")

    monkeypatch.setattr(quotes_service, "_provider", _Boom())

    assert quotes_service.get_live_quotes(db, ["ZZQ6"]) == {}


def test_unknown_symbols_are_absent_not_faked(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _SpyProvider({})
    monkeypatch.setattr(quotes_service, "_provider", spy)

    assert quotes_service.get_live_quotes(db, ["ZZNOSUCHSYMBOL"]) == {}
    assert spy.calls == []  # nothing to ask about, so no upstream call


def test_empty_input_short_circuits(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _SpyProvider({})
    monkeypatch.setattr(quotes_service, "_provider", spy)

    assert quotes_service.get_live_quotes(db, []) == {}
    assert spy.calls == []


def test_symbols_are_matched_case_insensitively(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _asset(db, "ZZQ7")
    spy = _SpyProvider({"NSE:ZZQ7": _quote("ZZQ7", 77.0)})
    monkeypatch.setattr(quotes_service, "_provider", spy)

    result = quotes_service.get_live_quotes(db, ["zzq7"])

    assert result["NSE:ZZQ7"].ltp == 77.0
